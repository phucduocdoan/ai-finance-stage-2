"""Thứ tự nào đưa bảng gold vào 3 khe evidence: judge chọn, hay reranker xếp?

`load_evidence` cắt `table_ids[:codegen_max_tables]` (mặc định 3), nên chỉ 3 bảng đầu của
`table_ids` là bằng chứng thật. Hôm nay `table_ids` = judge picks + mọi báo cáo chính còn
lại (`modules/rag/service.py:_evidence`), tức thứ tự do judge quyết.

`gate_shortlist_rank.py` đo 11 câu "ngoài shortlist" và thấy judge là chỗ nghẽn: 8/11 câu
có bảng gold trong cửa sổ 20 bảng mà judge đọc, thường ở hạng 0-3 của `pool.ranked`, mà
judge không chọn. Trên 11 câu đó judge chỉ chọn tổng 22 bảng, q306 chọn 0.

Gate này hỏi thẳng: nếu bỏ judge và lấy nguyên thứ tự reranker, bảng gold vào top-3 nhiều
hơn hay ít hơn? Đo trên cả 119 câu chấm được, không gọi LLM (chỉ `build_pool`).

Việc so sánh này chỉ đáng làm sau khi H1 đóng hướng TABLES: `table_ids` từng là thứ đem đi
nộp làm `relevant_tables`, giờ nó chấm 0.0 dù xếp thế nào, nên thứ tự của nó chỉ còn ảnh
hưởng tới solver.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_evidence_order.py
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_evidence_order.py --k 3,5,12
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gate_selection_vs_reading import locate  # type: ignore
from gate_shortlist_rank import RUN, SUBMISSION, run_scope  # type: ignore
from score_clean_eval import load_labels  # type: ignore

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.modules.rag.candidates import PRIMARY_STATEMENT_TYPES, rerank_with_picks
from finance_qa.modules.rag.service import get_retriever


def picks_of(table_ids: list[str], statement_types: dict[str, str]) -> list[str]:
    """Judge picks, gỡ lại từ `table_ids`.

    `_evidence` trả về `picks + [báo cáo chính chưa được chọn]`, nên phần đuôi toàn báo cáo
    chính là phần bù, còn lại là picks. Một pick *cũng có thể* là báo cáo chính, và khi đó
    nó bị tính lẫn vào đuôi. Sai lệch đó chỉ làm hybrid trông tệ hơn thực tế, vì pick bị
    mất quyền lên đầu, nên con số đo được là biên dưới.
    """
    cut = len(table_ids)
    while cut > 0 and statement_types.get(table_ids[cut - 1]) in PRIMARY_STATEMENT_TYPES:
        cut -= 1
    return table_ids[:cut]


def covered(order: list[str], gold: list[frozenset[str]], k: int) -> bool:
    """Mọi token gold có ít nhất một bảng trong `k` phần tử đầu.

    Đòi *mọi* token, vì thiếu một ô là thiếu bằng chứng: nhãn nhiều ô cần cả bộ.
    """
    head = set(order[:k])
    return bool(gold) and all(tabs & head for tabs in gold)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", default="1,3,5,12", help="các mốc top-K cần đo")
    ap.add_argument("--json", help="ghi kết quả từng câu ra file JSON")
    args = ap.parse_args()
    ks = [int(x) for x in args.k.split(",")]

    cfg = FinanceAgentConfig()
    labels = load_labels()
    submission = {int(it["id"]): it for it in json.loads(SUBMISSION.read_text())}
    run: dict[int, dict] = {}
    for line in RUN.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            run[record["id"]] = record

    ids = sorted(i for i in labels if labels[i].get("answer") is not None and i in submission)
    retriever = get_retriever(cfg.reranker, cfg.judge_top_n, cfg.dense_backend)

    orders_wanted = ("gửi", "ranked", "fused", "picks+ranked")
    hits = {name: dict.fromkeys(ks, 0) for name in orders_wanted}
    scorable = 0
    rows: dict[str, dict] = {}
    for i in ids:
        gold = [tabs for tabs in locate(labels[i]).values() if tabs]
        if not gold:
            continue
        record = run.get(i, {})
        tickers, years, doc_type = run_scope(record)
        if not tickers or not years:
            continue
        scorable += 1
        pool = retriever.build_pool({"question": submission[i].get("question") or "",
                                     "tickers": tickers, "years": years, "doc_type": doc_type})
        sent = list(record.get("table_ids") or [])
        orders = {
            "gửi": sent,
            "ranked": pool.ranked,
            # Thứ tự RRF trước khi reranker xếp lại, để biết công của reranker.
            "fused": pool.rankings.get("fused") or pool.ranked,
            # Judge picks lên đầu, phần còn lại giữ thứ tự reranker thay vì chỉ nhặt báo
            # cáo chính. Đây là thay đổi một dòng ở `_evidence` nếu nó thắng.
            "picks+ranked": rerank_with_picks(
                pool.ranked, picks_of(sent, retriever.statement_types)
            ),
        }
        row = {}
        for name, order in orders.items():
            for k in ks:
                ok = covered(order, gold, k)
                hits[name][k] += ok
                row[f"{name}@{k}"] = ok
        rows[str(i)] = row

    print(f"\n{scorable} câu dò được bảng gold, scope production, không gọi LLM\n")
    print(f"{'thứ tự':<10}" + "".join(f"{'top-' + str(k):>9}" for k in ks))
    for name in orders_wanted:
        cells = "".join(f"{hits[name][k]:>9}" for k in ks)
        print(f"{name:<10}{cells}")
    print(f"\ncodegen_max_tables = {cfg.codegen_max_tables}, tức cột top-"
          f"{cfg.codegen_max_tables} là số khe evidence thật")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
