"""Rule-based solver routing for the finance solve graph.

The router does not choose answers. It only walks enabled fail-closed solvers in
order, then falls through to selection fan-out or legacy codegen.
"""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.modules.solve.pipeline.outcome import solver_done
from finance_qa.modules.solve.solvers.decompose import axis_of


SOLVER_CHAIN: list[tuple[str, str, str]] = [
    ("cell_locator", "solve_single_cell", "cell_locator"),
    ("formula_facts", "solve_formula_facts", "formula_facts"),
    ("raw_table_linker", "solve_raw_table_linker", "raw_table_linker"),
    ("selection_facts", "solve_selection_facts", "selection_facts"),
    ("raw_selection_linker", "solve_raw_selection_linker", "raw_selection_linker"),
    ("structured_facts", "solve_structured_facts", "structured_facts"),
]


def selection_route(config: Any, state: Mapping[str, Any]) -> str:
    """Shared fallback once every enabled solver in ``SOLVER_CHAIN`` declined."""
    if not config.selection_decompose:
        return "generate_pandas"
    axis = axis_of(
        str(state["question"]), state.get("years") or [], state.get("tickers") or []
    )
    return "solve_selection" if axis else "generate_pandas"


def make_solver_router(config: Any, after: str | None):
    """Build a LangGraph conditional route after ``after``.

    ``after=None`` is the first route after retrieval. Later routes first check
    whether the solver that just ran marked ``diag[solver].done``.
    """
    start = 0
    diag_key = None
    if after is not None:
        start = 1 + next(i for i, (_, node, _) in enumerate(SOLVER_CHAIN) if node == after)
        diag_key = next(key for _, node, key in SOLVER_CHAIN if node == after)
    remaining = SOLVER_CHAIN[start:]

    def route(state: Mapping[str, Any]) -> str:
        if diag_key is not None and solver_done(state, diag_key):
            return "verify_answer"
        for flag, node, _ in remaining:
            if getattr(config, flag):
                return node
        return selection_route(config, state)

    destinations = [node for _, node, _ in remaining] + ["solve_selection", "generate_pandas"]
    if after is not None:
        destinations = ["verify_answer"] + destinations
    return route, destinations


def route_after_selection(state: Mapping[str, Any]) -> str:
    """Send completed selection fan-out to verify, otherwise fall back to codegen."""
    return "verify_answer" if solver_done(state, "selection") else "generate_pandas"


__all__ = [
    "SOLVER_CHAIN",
    "make_solver_router",
    "route_after_selection",
    "selection_route",
]
