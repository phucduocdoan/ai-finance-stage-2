"""Chạy lại đuôi tất định của pipeline trên 1012 câu, không gọi LLM.

Đo hiệu quả của phần vá "nhân *100 cho tỷ lệ data/data" trong `apply_units`
(`execute._is_data_ratio` / `execute._already_scaled_to_percent`). Cùng cách làm
với `gate_sign_replay.py`: nạp lại bản ghi run (giữ nguyên `solution` và
`table_ids`/`diag.evidence_tables`, tức mọi đầu vào của `apply_units`), nạp lại
bảng, gọi `apply_units` rồi `run_query` một lần với luật cũ (vô hiệu hoá
`_is_data_ratio`) và một lần với luật mới, rồi so hai bên. Không có model nào
được gọi, nên số ra được là tất định.

Chấm trên gold73 thật (`scripts/score_gold75.py`), không dùng tập proxy
`artifacts/eval_clean/` (nhãn Claude tạo, không đáng tin ở câu mơ hồ).

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/percent_scale_replay.py
"""
from __future__ import annotations

import json
from pathlib import Path

from score_gold75 import load_gold, close  # type: ignore

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen import execute
from finance_qa.modules.solve.codegen.execute import apply_units
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.tools.python_exec import run_query

RUN = Path("artifacts/runs/full1012_v17_unitfix.jsonl")


def replay(record: dict, *, new_rule: bool) -> float | None:
    solution = PandasSolution.model_validate(record["solution"])
    names, frames = {}, {}
    for i, table_id in enumerate((record.get("diag") or {}).get("evidence_tables") or [], 1):
        names[f"df{i}"] = table_id
        try:
            frames[f"df{i}"] = load_frame(table_id)
        except Exception:  # noqa: BLE001
            return None
    if not frames:
        return None

    saved = execute._is_data_ratio
    if not new_rule:
        execute._is_data_ratio = lambda *_: False  # type: ignore[assignment]
    try:
        query, _diag = apply_units(
            solution, frames,
            question=record.get("question") or "",
            names=names,
            tickers=[],
        )
    finally:
        execute._is_data_ratio = saved

    try:
        return float(run_query(query, dict(frames)))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    gold = load_gold()
    records = [json.loads(l) for l in RUN.read_text().splitlines() if l.strip()]
    # Filter on the *stored* record, not on `solution.target_unit`: that field is
    # the model's own self-declared unit, only a fallback -- `apply_units` (see
    # `unit_from_hint`, execute.py) resolves the real target from the question
    # text first, so a genuinely percent-targeted question routinely stores
    # `target_unit: "unknown"` here and still gets scaled correctly at runtime.
    records = [r for r in records if isinstance(r.get("solution"), dict)]

    replayed = flipped = 0
    old_score = new_score = 0
    scored_total = 0
    changed: list[tuple[int, float | None, float | None]] = []
    for record in records:
        qid = record["id"]
        old = replay(record, new_rule=False)
        new = replay(record, new_rule=True)
        if old is None and new is None:
            continue
        replayed += 1
        if old != new:
            flipped += 1
            changed.append((qid, old, new))
        if qid not in gold:
            continue
        scored_total += 1
        g = float(gold[qid]["gold_answer"])
        old_score += close(old, g, 0.01)
        new_score += close(new, g, 0.01)

    print(f"câu có solution để chạy lại: {len(records)}")
    print(f"chạy lại được {replayed}/{len(records)} câu, không gọi LLM")
    print(f"luật đổi kết quả ở {flipped} câu\n")
    print(f"trong gold73: {scored_total} câu có nhãn thật")
    print(f"chạy lại, luật cũ (không nhân x100)   {old_score}/{scored_total}")
    print(f"chạy lại, luật mới (item 7 đã vá)     {new_score}/{scored_total}\n")

    for qid, old, new in sorted(changed):
        mark = "trong gold73" if qid in gold else "không nhãn"
        gold_val = gold[qid]["gold_answer"] if qid in gold else None
        print(f"  q{qid} ({mark})\tcũ {old}\tmới {new}\tnhãn {gold_val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
