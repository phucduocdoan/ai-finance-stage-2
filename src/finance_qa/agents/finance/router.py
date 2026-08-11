"""Routing decisions for the finance graph."""

from __future__ import annotations

from langgraph.graph import END

from finance_qa.agents.finance.state import FinanceState


def route_after_load(state: FinanceState, *, formula_on: bool = True) -> str:
    op = state.get("operation", "")
    if op == "lookup" and state.get("answer_shape") == "single_cell":
        return "lookup"
    if formula_on and op in ("formula", "compare", "multi_step"):
        return "formula"
    return "repl"


def route_formula(state: FinanceState) -> str:
    return "repl" if state.get("solver") == "formula_skip" else END


def route_lookup(state: FinanceState) -> str:
    return "repl" if state.get("solver") == "lookup_failed" else END
