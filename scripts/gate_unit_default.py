"""Lớp "mặc định vnd": đơn vị nào mới đúng, và có tín hiệu nào đoán được nó không.

`resolve_source_unit` trả `vnd` khi không đọc được khai báo đơn vị nào, với lý do
"9 trong 12 bảng gold không khai đơn vị đều in VND thô". Lớp này bắn ở 396/838 câu
replay, và trên 119 câu sạch thì 20 đúng 37 sai, nên đảo mặc định là đổi 20 câu đúng
lấy 37 câu sai. Không đảo. Câu hỏi đúng phải là: ở những câu sai, đơn vị *thật* là
gì, và có tín hiệu tất định nào đọc ra được nó.

Kết quả (`artifacts/runs/gate_unit_default.out`): chỉ **2 trong 37 câu sai** là do
mặc định đơn vị (q139 muốn thousand_vnd, q284 muốn million_vnd). 35 câu còn lại không
có đơn vị nguồn nào trong `MONEY_SCALE` cho ra nhãn, tức đọc sai ô. Tín hiệu bảng anh
em đọc đúng q284 và đọc sai q139, thắng 1 trong 2. Manh mối chết, xem
`docs/answer_signatures_2026-08-22.md` §5.

Gate này chạy `apply_units` thật trên bản ghi run (không gọi LLM, xem
`gate_sign_replay.py` cho cách dựng lại `df1..dfN` và vì sao cần `names`), rồi với
mỗi câu sai trong lớp mặc định, thử lần lượt từng đơn vị nguồn trong `MONEY_SCALE`
và xem đơn vị nào cho ra nhãn. Đó là "đơn vị thật" mà pipeline lẽ ra phải đọc.

Ba tín hiệu ứng viên được đo cùng lúc, tất cả đều tất định:

- `khai bao cung bao cao`: bảng khác *cùng report_id* có khai đơn vị không. Báo cáo
  in đơn vị một lần ở đầu, nên bảng mất banner khi trích xuất vẫn có thể mượn của
  bảng anh em.
- `khai bao cung trang`: hẹp hơn, chỉ mượn của bảng cùng trang.
- `do lon`: số chữ số của giá trị thô. Đây là phỏng đoán theo độ lớn, đo để biết nó
  *có* tách được lớp hay không, chứ không phải để dùng ngay.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_unit_default.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from score_clean_eval import as_float, correct, load_labels, load_submission  # type: ignore

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen.execute import apply_units
from finance_qa.modules.solve.common.context import page_text
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.solve.common.units import (
    MONEY_SCALE,
    conversion_factor,
    detect_unit,
)
from finance_qa.modules.solve.common.units import strip_scale_factor
from finance_qa.modules.tools.python_exec import run_query

SUBMISSION = "output/submission_v9_sign/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")
DEFAULTED = "mặc định vnd"
TABLE_ID = re.compile(r"^(.*)\|(\d+)$")


def replay(record: dict) -> tuple[dict, float, str] | None:
    """(diag, giá trị *thô* trước khi đổi đơn vị, table_id của ô đích)."""
    solution = PandasSolution.model_validate(record.get("solution") or {})
    if not (solution.pandas_query or "").strip():
        return None
    frames, names = {}, {}
    for i, table_id in enumerate((record.get("diag") or {}).get("evidence_tables") or [], 1):
        names[f"df{i}"] = table_id
        try:
            frames[f"df{i}"] = load_frame(table_id)
        except Exception:  # noqa: BLE001
            return None
    if not frames:
        return None
    _, diag = apply_units(
        solution, frames, question=record.get("question") or "", names=names
    )
    # Giá trị *thô*: bỏ mọi phép nhân đơn vị, vì `true_unit` cần con số như bảng in.
    raw_query, _ = strip_scale_factor(solution.pandas_query)
    try:
        raw = float(run_query(raw_query, dict(frames)))
    except Exception:  # noqa: BLE001
        return None
    return diag, raw, names.get(solution.table_variable, "")


def sibling_unit(table_id: str, *, same_page_only: bool) -> str | None:
    """Đơn vị khai ở bảng khác cùng báo cáo (hoặc cùng trang), nếu có đúng một."""
    match = TABLE_ID.match(table_id)
    if not match:
        return None
    report, index = match.group(1), int(match.group(2))
    span = range(index - 1, index + 2) if same_page_only else range(max(1, index - 8), index + 9)
    found = set()
    for other in span:
        if other == index:
            continue
        other_id = f"{report}|{other}"
        try:
            frame = load_frame(other_id)
        except Exception:  # noqa: BLE001 - bảng không tồn tại
            continue
        unit, _ = detect_unit(frame, None, page_text(other_id))
        if unit:
            found.add(unit)
    return found.pop() if len(found) == 1 else None


def true_unit(raw: float, gold: float, target: str) -> str | None:
    """Đơn vị nguồn nào biến `raw` thành `gold`, nếu có."""
    for unit in MONEY_SCALE:
        value = raw * conversion_factor(unit, target)
        if gold == 0:
            continue
        if abs(value - gold) <= 0.01 * max(abs(value), abs(gold)):
            return unit
    return None


def main() -> int:
    labels = load_labels()
    sub = load_submission(SUBMISSION)
    records = [json.loads(l) for l in RUN.read_text().splitlines() if l.strip()]
    scored = {i for i, g in labels.items() if g.get("answer") is not None and i in sub}

    fired = replayed = 0
    inside: list[tuple[int, bool, dict, float, str]] = []
    for record in records:
        out = replay(record)
        if out is None:
            continue
        replayed += 1
        diag, raw, table_id = out
        if not str(diag.get("source_unit_from") or "").startswith(DEFAULTED):
            continue
        fired += 1
        qid = int(record["id"])
        if qid in scored:
            ok = correct(sub[qid].get("answer"), labels[qid]["answer"])
            inside.append((qid, ok, diag, raw, table_id))

    print(f"\nchạy lại được {replayed}/{len(records)} câu")
    print(f"lớp 'mặc định vnd' bắn ở {fired} câu ({fired / max(replayed, 1):.0%})")
    right = [q for q, ok, *_ in inside if ok]
    wrong = [(q, d, r, t) for q, ok, d, r, t in inside if not ok]
    print(f"trong 119 câu sạch: {len(inside)} câu, {len(right)} đúng, {len(wrong)} sai\n")

    print("câu sai: đơn vị nào mới cho ra nhãn, và tín hiệu có đọc ra không")
    hits = Counter()
    for qid, diag, raw, table_id in sorted(wrong):
        gold = as_float(labels[qid]["answer"]) or 0.0
        target = str(diag.get("target_unit") or "unknown")
        want = true_unit(raw, gold, target)
        report_signal = sibling_unit(table_id, same_page_only=False) if table_id else None
        page_signal = sibling_unit(table_id, same_page_only=True) if table_id else None
        hits[f"thật = {want}"] += 1
        if want and want != "vnd":
            hits["sai vì mặc định vnd"] += 1
            if report_signal == want:
                hits["báo cáo đọc đúng"] += 1
            if page_signal == want:
                hits["cùng trang đọc đúng"] += 1
        print(f"  q{qid:<4} thô {raw:>18.2f} -> nhãn {gold:<16} đích {target:<13}"
              f" thật {str(want):<14} báo cáo {str(report_signal):<14} trang {page_signal}")

    print()
    for key, n in hits.most_common():
        print(f"  {key:<26}{n:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
