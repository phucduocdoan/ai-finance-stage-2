"""Formula graph adapter.

Formula planning/execution lives in `finance_qa.modules.codegen.formula`; this
file only adapts FinanceState/config to a LangGraph node patch.
"""
from __future__ import annotations

from finance_qa.agents.finance.state import FinanceState
from finance_qa.modules.codegen.service import generate_formula_solution


def make_formula_solver(cfg):
    """Build the formula solver node bound to agent config `cfg`."""

    def formula_solver(state: FinanceState) -> dict:
        return generate_formula_solution(
            question=state["question"],
            frames=state.get("frames") or {},
            names=state.get("names") or {},
            tickers=state.get("tickers") or [],
            years=state.get("years") or [],
            unit_hint=state.get("unit_hint") or "",
            errors=list(state.get("errors") or []),
            thinking=cfg.formula_thinking,
            max_tokens=cfg.formula_max_tokens,
        )

    return formula_solver
