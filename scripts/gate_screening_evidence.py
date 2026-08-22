"""Câu sàng lọc mất công ty ở khâu nào: understand, budget, hay sinh code.

`gate_screening_class.py` đo ra lớp sàng lọc đúng 4/29 trong khi phần còn lại đúng
45/90, và 31 trong 42 câu tỉ lệ trả > 1e6 chỉ là một ô đơn `df1.iloc[k][col]`. Nhưng
"codegen trả một ô của một công ty" chưa nói fix nằm ở đâu: nếu bằng chứng đưa vào
prompt đã thiếu công ty thì không solver nào giải được, và phải sửa retrieval hoặc
`codegen_budget`, không phải tầng solve.

Bản ghi run đủ để tách ba khâu, không cần gọi LLM:

- `scope`  = mã đọc từ report_id trong `record["table_ids"]`. Lọc cứng chỉ cho qua
  bảng khớp scope, nên tập report này *là* danh sách mã understand chọn.
- `evidence` = mã trong `diag["evidence_tables"]`, tức `df1..dfN` mà codegen thật sự
  nhìn thấy sau khi `codegen_budget` xoay vòng và cắt theo `max_tables`.
- `used`   = mã của những `dfK` xuất hiện trong `solution.pandas_query`.

scope thiếu thì lỗi ở understand. scope đủ mà evidence thiếu thì lỗi ở budget. Cả hai
đủ mà used thiếu thì lỗi ở sinh code. Ba trường hợp cần ba fix khác nhau.

Một cái bẫy đã dính: `evidence_tables` rỗng *không* phải bảng bị cắt hết. 102 trong
1012 câu rỗng, và tất cả đều do `selection_facts` hoặc `formula_facts` giải, tức
codegen không chạy nên không ghi evidence. Chỉ so ba khâu ở câu codegen thật sự chạy.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_screening_evidence.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from score_clean_eval import correct, load_labels, load_submission  # type: ignore

sys.path.insert(0, "scripts")
from gate_screening_class import is_screening  # noqa: E402

SUBMISSION = "output/submission_v9_sign/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")
TICKER_IN_REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_")
DF_NAME = re.compile(r"\bdf(\d+)\b")


def tickers_of(table_ids: list[str]) -> set[str]:
    return set(TICKER_IN_REPORT.findall(" ".join(table_ids)))


def stage(record: dict) -> tuple[set[str], set[str], set[str]]:
    """(scope, evidence, used) tính theo mã cổ phiếu."""
    evidence_tables = list((record.get("diag") or {}).get("evidence_tables") or [])
    query = str((record.get("solution") or {}).get("pandas_query") or "")
    used_tables = [
        evidence_tables[int(n) - 1]
        for n in set(DF_NAME.findall(query))
        if 0 < int(n) <= len(evidence_tables)
    ]
    return (
        tickers_of(list(record.get("table_ids") or [])),
        tickers_of(evidence_tables),
        tickers_of(used_tables),
    )


def main() -> int:
    labels = load_labels()
    sub = load_submission(SUBMISSION)
    scored = {i for i, g in labels.items() if g.get("answer") is not None and i in sub}
    records = [json.loads(l) for l in RUN.read_text().splitlines() if l.strip()]
    screening = [r for r in records if is_screening(str(r.get("question") or ""))]

    blame: Counter[str] = Counter()
    rows = []
    for record in screening:
        scope, evidence, used = stage(record)
        if not (record.get("diag") or {}).get("evidence_tables"):
            where = f"codegen không chạy ({record.get('solver')})"
        elif not scope:
            where = "không đọc được scope"
        elif len(scope) < 3:
            where = "understand thu scope < 3 mã"
        elif evidence < scope:
            where = "budget cắt mất công ty"
        elif len(used) < len(scope):
            where = "sinh code chỉ dùng một phần"
        else:
            where = "đủ cả ba khâu"
        blame[where] += 1
        rows.append((int(record["id"]), where, scope, evidence, used))

    print(f"\n{len(screening)} câu sàng lọc trong {len(records)} câu\n")
    for where, n in blame.most_common():
        ids = [q for q, w, *_ in rows if w == where]
        inside = [q for q in ids if q in scored]
        ok = sum(correct(sub[q].get("answer"), labels[q]["answer"]) for q in inside)
        label = f"{ok}/{len(inside)}" if inside else "-"
        print(f"  {where:<30}{n:>4} câu   có nhãn {label}")

    print("\n29 câu sàng lọc có nhãn, từng câu:")
    for qid, where, scope, evidence, used in sorted(rows):
        if qid not in scored:
            continue
        ok = correct(sub[qid].get("answer"), labels[qid]["answer"])
        print(f"  q{qid:<5}{'đúng' if ok else 'sai ':<5}scope {len(scope):>2}"
              f"  evidence {len(evidence):>2}  used {len(used):>2}   {where}")
        if evidence < scope:
            print(f"        mất: {sorted(scope - evidence)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
