"""Chạy lại đuôi tất định của pipeline trên 1012 câu, không gọi LLM.

`gate_sign_rule.py` đo luật dấu bằng cách lấy `abs()` con số đã nộp. Đúng phép về
số học, nhưng nó *không* chạy code thật: nó không biết `apply_units` bọc `abs`
vào đâu, không biết `as_magnitude` có bắn hay không, và không thấy `target_row`.

Gate này chạy code thật. Bản ghi run giữ nguyên `solution` (pandas_query,
source_unit, target_unit, target_row) và `table_ids`, tức mọi đầu vào của
`apply_units`. Nạp lại bảng, gọi `apply_units` rồi `run_query`, một lần với luật
mới và một lần với luật cũ (vô hiệu hoá `between_two_companies` và `PAID_OUT`),
rồi so hai bên. Không có model nào được gọi, nên số ra được là tất định.

Giới hạn đã biết: bản ghi run không lưu `state["tickers"]`, nên số mã đọc lại từ
`report_id` trong `table_ids` (lọc cứng chỉ cho qua bảng khớp scope, nên tập
report *là* danh sách mã understand chọn). Và chỉ những câu do codegen /
raw_table_linker giải mới chạy lại được: solver dòng thô ghi truy vấn theo df
khác, còn `decompose` không ghi truy vấn tổng nào. Câu nào không chạy lại được
thì bị bỏ, và số bỏ được in ra.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_sign_replay.py
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_sign_replay.py --show
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from score_clean_eval import as_float, correct, load_labels, load_submission  # type: ignore

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen import execute
from finance_qa.modules.solve.codegen.execute import apply_units
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.tools.python_exec import run_query

SUBMISSION = "output/submission_v8_round2/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")
TICKER_IN_REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_")
NEVER = re.compile(r"(?!x)x")


def tickers_of(table_ids: list[str]) -> list[str]:
    """Mã cổ phiếu trong scope, đọc lại từ report_id."""
    return sorted(set(TICKER_IN_REPORT.findall(" ".join(table_ids))))


def replay(record: dict, *, new_rule: bool) -> tuple[float | None, bool]:
    """Đáp án khi chạy lại đuôi tất định. Trả về (giá trị, luật độ lớn có bắn)."""
    solution = PandasSolution.model_validate(record["solution"])
    frames = {}
    # `diag["evidence_tables"]` là `names.values()` của graph, tức đúng df1..dfN mà
    # codegen đã thấy. `record["table_ids"]` là danh sách retrieval *trước* khi
    # `codegen_budget` xoay vòng và cắt theo `max_tables`, nên dùng nó thì 106/400
    # truy vấn KeyError vì số hiệu df lệch. `names` phải truyền vào `apply_units`
    # nữa: đơn vị tra trong page text của bảng đi qua nó, thiếu nó thì q744 rơi về
    # "mặc định vnd" rồi bị chia thêm 1e6.
    names = {}
    for i, table_id in enumerate((record.get("diag") or {}).get("evidence_tables") or [], 1):
        names[f"df{i}"] = table_id
        try:
            frames[f"df{i}"] = load_frame(table_id)
        except Exception:  # noqa: BLE001 - bảng thiếu thì câu đó bỏ qua
            return None, False
    if not frames:
        return None, False

    saved = (execute.between_two_companies, execute.PAID_OUT)
    if not new_rule:
        execute.between_two_companies = lambda *_: False  # type: ignore[assignment]
        execute.PAID_OUT = NEVER  # type: ignore[assignment]
    try:
        query, diag = apply_units(
            solution, frames,
            question=record.get("question") or "",
            names=names,
            tickers=tickers_of(record.get("table_ids") or []),
        )
    finally:
        execute.between_two_companies, execute.PAID_OUT = saved

    try:
        return float(run_query(query, dict(frames))), bool(diag.get("magnitude_abs"))
    except Exception:  # noqa: BLE001 - truy vấn lỗi thì không so được
        return None, bool(diag.get("magnitude_abs"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="in từng câu bị luật đổi")
    args = ap.parse_args()

    labels = load_labels()
    sub = load_submission(SUBMISSION)
    records = [json.loads(l) for l in RUN.read_text().splitlines() if l.strip()]
    records = [r for r in records if isinstance(r.get("solution"), dict)]

    scored = sorted(i for i, g in labels.items() if g.get("answer") is not None and i in sub)
    submitted = {i: correct(sub[i].get("answer"), labels[i]["answer"]) for i in scored}

    old_score = new_score = drift = replayed = flipped = 0
    changed: list[tuple[int, float | None, float | None]] = []
    for record in records:
        qid = record["id"]
        old, _ = replay(record, new_rule=False)
        new, fires = replay(record, new_rule=True)
        if old is None and new is None:
            continue
        replayed += 1
        if old != new:
            flipped += 1
            changed.append((qid, old, new))
        if qid not in scored:
            continue
        gold = labels[qid]["answer"]
        old_ok, new_ok = correct(old, gold), correct(new, gold)
        old_score += old_ok
        new_score += new_ok
        if old_ok != submitted[qid]:
            drift += 1

    print(f"\nchạy lại được {replayed}/{len(records)} câu có solution, không gọi LLM")
    print(f"luật đổi kết quả ở {flipped} câu\n")
    print(f"submission gốc        {sum(submitted.values())}/{len(scored)}")
    print(f"chạy lại, luật cũ     {old_score}/{len(scored)}   (lệch submission {drift} câu)")
    print(f"chạy lại, luật mới    {new_score}/{len(scored)}\n")

    inside = [(q, o, n) for q, o, n in changed if q in scored]
    for qid, old, new in sorted(inside):
        gold = labels[qid]["answer"]
        old_ok, new_ok = correct(old, gold), correct(new, gold)
        mark = "được" if new_ok and not old_ok else "mất" if old_ok and not new_ok else "không đổi"
        print(f"  q{qid} {mark}\tcũ {old}\tmới {new}\tnhãn {gold}")
    if args.show:
        print()
        for qid, old, new in sorted(q for q in changed if q[0] not in scored):
            print(f"  q{qid} (không nhãn)\tcũ {old}\tmới {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
