"""Bảng gold nằm ở hạng nào của retrieval, cho 11 câu "ngoài shortlist".

`gate_selection_vs_reading.py` chia 73 câu sai của v8 thành ba lớp, và lớp cuối chưa ai đo:
11 câu mà bảng gold **không** có trong `table_ids`, nên bộ chấm ô có hoàn hảo cũng vô ích.
Gate này hỏi đúng một câu: retrieval xếp bảng gold ở đâu, và cái gì cắt nó mất.

Đường đi của một bảng, theo `modules/rag/candidates.py`:

    lọc cứng (mã/năm/loại)  ->  pool.keys        ~106 bảng
    BM25 top-20 + dense top-20 -> RRF            CHANNEL_K = 20 mỗi kênh
    + mọi báo cáo chính trong keys                add_primary_statements
    reranker qwen3-0.6b xếp lại                   pool.ranked
    judge đọc 20 bảng đầu                         judge_top_n = 20
    picks + báo cáo chính còn lại                 table_ids, đem đi nộp

Bốn chỗ có thể mất bảng gold, và mỗi chỗ dẫn tới một việc khác hẳn nhau:

- `ngoài keys`      lọc cứng đánh rơi -> lỗi metadata hoặc scope, không phải xếp hạng
- `ngoài ranked`    trong keys nhưng không kênh nào đưa vào top-20 -> nâng `channel_k`;
                    gate in luôn hạng sâu của cả hai kênh nên biết cần nâng tới bao nhiêu
- `ngoài top-20`    reranker đẩy xuống dưới cửa sổ judge -> `judge_top_n` hoặc reranker
- `judge bỏ`        judge thấy mà không chọn -> lỗi judge, đắt nhất để sửa

Scope (mã, năm, hợp nhất/riêng) lấy từ `report_id` của nhãn, tức cho không bước understand,
để mọi thứ đo được là của riêng retrieval. Không gọi LLM: chỉ `build_pool`, không `select`.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_shortlist_rank.py
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_shortlist_rank.py --ids 267,306
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from gate_selection_vs_reading import locate  # type: ignore
from score_clean_eval import load_labels  # type: ignore

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.modules.rag.service import get_retriever

RUN = Path("artifacts/runs/full1012_v7.jsonl")
SUBMISSION = Path("output/submission_v8_round2/submission.json")
REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_(\d{4})(?:_([a-z]+))?")
# 11 câu "ngoài shortlist" của v8, từ `gate_selection_vs_reading.py`.
DEFAULT_IDS = [267, 306, 336, 523, 585, 596, 649, 714, 727, 769, 821]


def scope(label: dict) -> tuple[list[str], list[int], str]:
    """Mã, năm và loại báo cáo lấy thẳng từ nhãn, tức scope đúng được cho không."""
    hits = REPORT.findall(str(label.get("report_id") or ""))
    tickers = list(dict.fromkeys(t for t, _, _ in hits))
    years = list(dict.fromkeys(int(y) for _, y, _ in hits))
    kinds = {k for _, _, k in hits if k in {"consolidated", "separate"}}
    return tickers, years, kinds.pop() if len(kinds) == 1 else "unknown"


def run_scope(record: dict) -> tuple[list[str], list[int], str]:
    """Scope mà production thật sự dùng, đọc lại từ `report_id` của `table_ids`.

    Run không lưu output của node understand, nhưng lọc cứng chỉ cho qua bảng khớp scope,
    nên tập report của `table_ids` *là* scope đó. Cần con số này vì scope từ nhãn hẹp hơn ở
    câu nhiều năm: nhãn q523 chỉ ghi DCM_2023 còn câu hỏi trải 5 năm, nên pool từ nhãn dễ
    hơn pool thật và verdict "judge bỏ" đo trên nó sẽ lạc quan quá.
    """
    hits = REPORT.findall(" ".join(record.get("table_ids") or []))
    tickers = sorted({t for t, _, _ in hits})
    years = sorted({int(y) for _, y, _ in hits})
    kinds = {k for _, _, k in hits if k in {"consolidated", "separate"}}
    return tickers, years, kinds.pop() if len(kinds) == 1 else "unknown"


def deep_channels(retriever, pool) -> dict[str, dict[str, int]]:
    """Hạng của mọi key trong từng kênh khi *không* cắt ở `channel_k`.

    Đây là con số quyết định cho lớp `ngoài ranked`: nếu bảng gold ở hạng 25 của BM25 thì
    nâng `channel_k` là xong; nếu nó ở hạng 400 thì phải đổi index, đắt hơn nhiều.
    """
    out: dict[str, dict[str, int]] = {}
    keys = pool.keys
    if retriever.bm25 is not None:
        ordered = [k for k, _ in retriever.bm25.top_k(pool.query, keys, k=len(keys))]
        out["bm25"] = {key: i for i, key in enumerate(ordered)}
    if retriever._dense is not None:
        vecs, row_of = retriever._dense
        qvec = retriever._encode([pool.query])[0]
        rows = np.array([row_of[key] for key in keys])
        sims = vecs[rows].astype(np.float32) @ qvec.astype(np.float32)
        out["dense"] = {keys[i]: r for r, i in enumerate(np.argsort(-sims))}
    return out


def place(key: str, pool, deep, judge_top_n: int, table_ids: list[str]) -> tuple[str, str]:
    """Nhóm của một bảng gold, và một dòng chi tiết để in."""
    where = {
        "keys": pool.keys.index(key) if key in pool.keys else None,
        "ranked": pool.ranked.index(key) if key in pool.ranked else None,
        "sent": table_ids.index(key) if key in table_ids else None,
    }
    ranks = {name: order.get(key) for name, order in deep.items()}
    detail = (
        f"keys {where['keys']}  bm25 {ranks.get('bm25')}  dense {ranks.get('dense')}"
        f"  ranked {where['ranked']}  gửi {where['sent']}"
    )
    if where["keys"] is None:
        return "ngoài keys", detail
    if where["ranked"] is None:
        return "ngoài ranked", detail
    if where["sent"] is not None:
        return "đã gửi", detail
    if where["ranked"] >= judge_top_n:
        return "ngoài top-20", detail
    return "judge bỏ", detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="mặc định là 11 câu ngoài shortlist")
    ap.add_argument("--json", help="ghi kết quả ra file JSON")
    ap.add_argument("--scope", choices=["label", "run"], default="label",
                    help="label: cho không scope đúng. run: scope production thật đã dùng")
    args = ap.parse_args()

    cfg = FinanceAgentConfig()
    labels = load_labels()
    submission = {int(it["id"]): it for it in json.loads(SUBMISSION.read_text())}
    run: dict[int, dict] = {}
    for line in RUN.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            run[record["id"]] = record

    ids = [int(x) for x in args.ids.split(",")] if args.ids else DEFAULT_IDS
    ids = [i for i in ids if i in labels and i in submission]

    retriever = get_retriever(cfg.reranker, cfg.judge_top_n, cfg.dense_backend)
    tally: Counter[str] = Counter()
    out: dict[str, dict] = {}
    for i in ids:
        label = labels[i]
        record = run.get(i, {})
        tickers, years, doc_type = (
            run_scope(record) if args.scope == "run" else scope(label)
        )
        question = submission[i].get("question") or ""
        pool = retriever.build_pool(
            {"question": question, "tickers": tickers, "years": years, "doc_type": doc_type}
        )
        deep = deep_channels(retriever, pool)
        table_ids = list(record.get("table_ids") or [])
        found = locate(label)

        print(f"\nq{i} {question[:104]}")
        print(f"  scope {tickers} {years} {doc_type}"
              f"  keys {len(pool.keys)}  ranked {len(pool.ranked)}  gửi {len(table_ids)}")
        groups: list[str] = []
        rows: list[dict] = []
        for token, holder_set in sorted(found.items()):
            if not holder_set:
                print(f"  {token:>22}  không dò được bảng nào")
                continue
            # Bảng gold tốt nhất cho token này: nhãn nhiều ô đòi mọi token có bảng, nhưng
            # một token có thể nằm ở nhiều bảng và chỉ cần một bảng vào được là đủ.
            best = min(
                sorted(holder_set),
                key=lambda k: (
                    pool.ranked.index(k) if k in pool.ranked
                    else (10_000 + pool.keys.index(k) if k in pool.keys else 100_000)
                ),
            )
            group, detail = place(best, pool, deep, cfg.judge_top_n, table_ids)
            groups.append(group)
            rows.append({"token": token, "table": best, "group": group, "detail": detail,
                         "n_holders": len(holder_set)})
            print(f"  {token:>22}  {group:<12} {best}  ({len(holder_set)} bảng chứa)")
            print(f"  {'':>22}  {detail}")
        # Nhóm của câu lấy theo token *tệ nhất*: thiếu một ô là thiếu bằng chứng.
        order = ["ngoài keys", "ngoài ranked", "ngoài top-20", "judge bỏ", "đã gửi"]
        worst = min(groups, key=order.index) if groups else "không dò được"
        tally[worst] += 1
        out[str(i)] = {"group": worst, "tokens": rows,
                       "n_keys": len(pool.keys), "n_ranked": len(pool.ranked)}

    print(f"\n{len(ids)} câu, scope cho không từ nhãn, không gọi LLM\n")
    for group in ["ngoài keys", "ngoài ranked", "ngoài top-20", "judge bỏ", "đã gửi",
                  "không dò được"]:
        if tally[group]:
            hit = sorted(int(i) for i, v in out.items() if v["group"] == group)
            print(f"  {group:<14}{tally[group]:>4}  {hit}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
