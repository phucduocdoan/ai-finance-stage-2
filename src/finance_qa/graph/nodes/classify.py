"""Classify node: enrich state with question metadata."""
from __future__ import annotations

import json

from finance_qa.graph.state import FinanceState
from finance_qa.paths import QUESTION_METADATA_PATH

_META: dict[int, dict] | None = None


def _load_meta() -> dict[int, dict]:
    global _META
    if _META is None:
        with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
            _META = {int(r["id"]): r for r in map(json.loads, filter(str.strip, fh))}
    return _META


def classify(state: FinanceState) -> dict:
    meta = _load_meta().get(state["id"], {})
    return {
        "answer_shape": meta.get("answer_shape", "derived"),
        "multi_year":   bool(meta.get("multi_year", False)),
        "multi_company": bool(meta.get("multi_company", False)),
        "tickers":      meta.get("tickers") or [],
        "years":        meta.get("years") or [],
        "unit_hint":    meta.get("unit_hint") or "",
    }
