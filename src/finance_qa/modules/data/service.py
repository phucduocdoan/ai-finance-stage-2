"""Public data service used by graph and batch pipelines."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from finance_qa.modules.data.table_store import load_frame


def ordered_table_names(table_ids: list[str]) -> dict[str, str]:
    """Map table ids to stable df variable names in table-position order."""

    def _pos(table_id: str) -> int:
        try:
            return int(table_id.rsplit("|", 1)[1])
        except (IndexError, ValueError):
            return 999

    return {
        f"df{i}": table_id
        for i, table_id in enumerate(sorted(table_ids, key=_pos), 1)
    }


def load_tables(table_ids: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str]]:
    """Load evaluator-facing frames for ``table_ids``."""
    names = ordered_table_names(table_ids)
    frames: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    for var, table_id in names.items():
        try:
            frames[var] = load_frame(table_id)
        except Exception as exc:  # noqa: BLE001 - surfaced in graph state
            errors.append(f"load: {table_id} -> {exc}")
    return frames, names, errors


def load_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """LangGraph node wrapper for the data service."""
    frames, names, load_errors = load_tables(list(state.get("table_ids") or []))
    return {
        "frames": frames,
        "names": names,
        "errors": list(state.get("errors") or []) + load_errors,
    }

