"""Load node: materialise DataFrames from table_ids."""
from __future__ import annotations

from finance_qa.execution.query import load_frame
from finance_qa.graph.state import FinanceState


def load(state: FinanceState) -> dict:
    table_ids = state.get("table_ids") or []

    def _pos(tid: str) -> int:
        try:
            return int(tid.rsplit("|", 1)[1])
        except (IndexError, ValueError):
            return 999

    sorted_ids = sorted(table_ids, key=_pos)
    names: dict[str, str] = {f"df{i}": tid for i, tid in enumerate(sorted_ids, 1)}
    frames: dict = {}
    errors = list(state.get("errors") or [])

    for var, tid in names.items():
        try:
            frames[var] = load_frame(tid)
        except Exception as exc:
            errors.append(f"load: {tid} -> {exc}")

    return {"frames": frames, "names": names, "errors": errors}
