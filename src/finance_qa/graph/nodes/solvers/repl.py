"""REPL solver: interactive exploration, best for derived/multi-year/multi-company.

Calls repl_generate() directly with already-loaded frames (skips redundant I/O).
"""
from __future__ import annotations

from finance_qa.graph.state import FinanceState
from finance_qa.planning.repl import repl_generate


def repl_solver(state: FinanceState) -> dict:
    frames = state.get("frames") or {}
    names  = state.get("names") or {}

    if not frames:
        return {
            "answer": 0.0, "pandas_query": "0.0", "evidence": [],
            "solver": "repl",
            "errors": (state.get("errors") or []) + ["repl: no frames loaded"],
        }

    result = repl_generate(
        question=state["question"],
        frames=frames,
        names=names,
    )
    return {
        "answer":       float(result.get("answer") or 0.0),
        "pandas_query": result.get("pandas_query") or "0.0",
        "evidence":     result.get("evidence") or [],
        "solver":       "repl",
        "errors":       (state.get("errors") or []) + (
            [result["error"]] if result.get("error") else []
        ),
    }
