"""Throwaway A/B harness for judge prompt/config variants.

Runs against the pools cached in /tmp/pools.json so each variant costs only the
LLM calls -- no re-embedding, no BM25 rebuild. Scored exactly like
eval_retrieval.py (recall@K over interchangeable-id groups) so numbers are
comparable across the two.

  .venv_bge/bin/python scripts/judge_ab.py
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import _bootstrap  # noqa: F401

from finance_qa.evaluation.retrieval import recall_at_k
from finance_qa.modules.rag import judge as llm_judge

BASE_PROMPT = llm_judge.PROMPT  # captured before any variant overwrites it

POOLS_PATH = Path("/tmp/pools.json")
KS = (5, 10, 15)
WORKERS = 4  # shared vLLM instance, keep it polite

# MEASURED AND REJECTED, kept so it isn't retried. Hypothesis was that the baseline
# prompt's "không chọn thừa" made the judge under-select on multi-year questions;
# this variant tells it to count the required tables first and to err toward
# including. It lost both times (picks only 53.3% / 58.7% vs 57-64% for baseline).
# The hypothesis was wrong: per-question numbers show multi-group questions were
# already fine (#818 5/5, #524 5/5) and the failures were single-table questions
# where the judge picked the *wrong* table -- a truncation problem, not a count one.
PROMPT_RECALL = """Bạn đang chọn bảng dữ liệu (table) làm bằng chứng để trả lời một câu hỏi tài chính.

CÂU HỎI: {question}

DANH SÁCH BẢNG ỨNG VIÊN (mỗi dòng: [số] report_id | tiêu đề và nhãn dòng của bảng):
{candidates}

Nhiệm vụ: chọn ĐẦY ĐỦ các bảng chứa số liệu cần để trả lời.

Trước khi chọn, hãy xác định: câu hỏi cần bao nhiêu bảng?
- Mỗi NĂM được hỏi cần bảng riêng của năm đó. Hỏi 5 năm thì phải có 5 bảng.
- Mỗi CHỈ TIÊU nằm ở báo cáo khác nhau cần bảng riêng (vd doanh thu ở KQKD, tổng tài sản ở CĐKT).
- Bảng cân đối kế toán thường bị tách 2 phần: TÀI SẢN và NỢ PHẢI TRẢ + VỐN CHỦ SỞ HỮU.
Rồi chọn đủ số bảng đó.

- `report_id` cho biết mã cổ phiếu, năm, và loại báo cáo (consolidated = hợp nhất, separate = riêng/công ty mẹ).
- Nếu lưỡng lự giữa 2 bảng cùng phục vụ một số liệu, chọn CẢ HAI — thiếu bảng thì không trả lời được, còn thừa một bảng thì vô hại.
- Xếp bảng chắc chắn nhất lên đầu. Tối đa {max_picks} bảng.

Chỉ in ra JSON, không giải thích:
{{"picks": [số, số, ...]}}"""


# The failure mode the per-question dump exposed: on 4 of the 5 remaining misses the
# judge picked the *detail note* while GT is the primary statement (#752 picked "LÃI
# THUẦN TỪ HOẠT ĐỘNG DỊCH VỤ" over BÁO CÁO KQKD; #582 picked "Phải trả khác / Vay
# ngắn hạn" over BẢNG CÂN ĐỐI KẾ TOÁN). Both tables really do carry the number, so
# this is a labelling convention, not a reasoning error -- the GT annotator reads the
# line item off the primary statement. Cheapest possible fix: tell the judge to take
# both, primary first. #100 is the mirror image (GT is the note), which is why the
# rule is "chọn cả hai" and not "chỉ chọn báo cáo chính".
PROMPT_BOTH = """Bạn đang chọn bảng dữ liệu (table) làm bằng chứng để trả lời một câu hỏi tài chính.

CÂU HỎI: {question}

DANH SÁCH BẢNG ỨNG VIÊN (mỗi dòng: [số] report_id | tiêu đề và nhãn dòng của bảng):
{candidates}

Nhiệm vụ: chọn TẤT CẢ các bảng chứa số liệu cần để trả lời.
- `report_id` cho biết mã cổ phiếu, năm, và loại báo cáo (consolidated = hợp nhất, separate = riêng/công ty mẹ).
- Nếu câu hỏi trải nhiều năm, phải chọn bảng của TỪNG năm được hỏi.
- Nếu cần nhiều chỉ tiêu ở các bảng khác nhau, chọn tất cả các bảng đó.
- Một chỉ tiêu thường xuất hiện ở CẢ báo cáo chính (BẢNG CÂN ĐỐI KẾ TOÁN, BÁO CÁO KẾT QUẢ
  HOẠT ĐỘNG KINH DOANH, BÁO CÁO LƯU CHUYỂN TIỀN TỆ) LẪN thuyết minh chi tiết. Khi đó chọn
  CẢ HAI, và xếp bảng báo cáo chính lên trước.
- Nếu một thuyết minh bị tách nhiều phần ("(tiếp theo)"), chọn phần chứa dòng tổng hợp trước.
- Xếp bảng chắc chắn nhất lên đầu. Chọn tối đa {max_picks} bảng.

Chỉ in ra JSON, không giải thích:
{{"picks": [số, số, ...]}}"""


def run(
    pools: list[dict],
    label: str,
    thinking: bool = False,
    window: int | None = None,
    doc_chars: int | None = None,
    prompt: str | None = None,
) -> None:
    tbl = [p for p in pools if p["gt_tables"]]
    # None means "use the budgeted CAP_LADDER", which is the current default --
    # `doc_chars or 400` silently made every unlabelled run a 400-char run.
    llm_judge.DOC_CHARS = doc_chars
    llm_judge.PROMPT = prompt or BASE_PROMPT

    def one(p):
        pool = [(k, p["doc_text"][k]) for k in p["rrf"]]
        if window:
            # Two stages: cheap windowed sieve to fight attention dilution over
            # ~70 candidates, then one thinking pass to rank the survivors.
            survivors = []
            for s in range(0, len(pool), window):
                survivors += llm_judge.judge(p["question"], pool[s : s + window])
            sub = [(k, p["doc_text"][k]) for k in survivors]
            picks = llm_judge.judge(p["question"], sub, thinking=thinking)
        else:
            picks = llm_judge.judge(p["question"], pool, thinking=thinking)
        ranked = picks + [k for k in p["rrf"] if k not in set(picks)]
        return p, picks, ranked

    t0 = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(one, tbl))
    dt = time.perf_counter() - t0

    rec = {k: 0.0 for k in KS}
    allh = {k: 0 for k in KS}
    npicks = []
    for p, picks, ranked in results:
        npicks.append(len(picks))
        for k in KS:
            r, a = recall_at_k(ranked, p["gt_tables"], k)
            rec[k] += r / len(tbl)
            allh[k] += a / len(tbl)

    # `picks only` is what submission actually gets: relevant_tables = the picks,
    # with no retrieval tail to pad the deeper Ks. The @K columns above always
    # include that tail, so they flatter the judge.
    pk = sum(recall_at_k(p, g, len(p))[0] if p else 0.0
             for (_, p, _), g in zip(results, (x["gt_tables"] for x in tbl))) / len(tbl)
    pka = sum(recall_at_k(p, g, len(p))[1] if p else False
              for (_, p, _), g in zip(results, (x["gt_tables"] for x in tbl))) / len(tbl)
    picks_str = f"picks med {sorted(npicks)[len(npicks) // 2]}"
    print(f"{label:28} " + "  ".join(f"@{k} {rec[k]:5.1%}/{allh[k]:5.1%}" for k in KS)
          + f"  | picks only {pk:5.1%}/{pka:5.1%}  | {picks_str}, {dt:.0f}s")
    misses = [p["qid"] for p, _, r in results if recall_at_k(r, p["gt_tables"], 15)[0] < 1]
    print(f"{'':28} misses@15: {misses}")


def main() -> int:
    pools = json.loads(POOLS_PATH.read_text(encoding="utf-8"))
    # Current default (no truncation, thinking on) vs the two variants it beat.
    run(pools, "default", thinking=True)
    run(pools, "both (primary+note)", thinking=True, prompt=PROMPT_BOTH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
