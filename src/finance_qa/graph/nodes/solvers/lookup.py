"""Lookup solver: planner-based, best for single_cell questions.

Wraps the existing planning.generator.generate() with planner=True, no REPL fallback.
If planner returns 0 or errors, the graph can route to repl_solver as a second attempt.
"""
from __future__ import annotations

from finance_qa.graph.state import FinanceState
from finance_qa.planning.generator import generate


def lookup_solver(state: FinanceState) -> dict:
    result = generate(
        question=state["question"],
        table_ids=state.get("table_ids") or [],
        use_planner=True,
        fallback=False,   # no REPL here — graph routes to repl on failure
    )
    failed = bool(result.get("error"))
    return {
        "answer":       float(result.get("answer") or 0.0),
        "pandas_query": result.get("pandas_query") or "0.0",
        "evidence":     result.get("evidence") or [],
        "solver":       "lookup_failed" if failed else "lookup",
        "errors":       (state.get("errors") or []) + (
            [result["error"]] if failed else []
        ),
    }
