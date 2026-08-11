"""REPL graph adapter.

The tool-calling REPL implementation lives in `finance_qa.modules.codegen.repl`.
This file only adapts FinanceState to a LangGraph node patch.
"""
from __future__ import annotations

from finance_qa.agents.finance.state import FinanceState
from finance_qa.modules.codegen.service import agenerate_repl_solution


async def repl_solver(state: FinanceState) -> dict:
    return await agenerate_repl_solution(
        question=state["question"],
        frames=state.get("frames") or {},
        names=state.get("names") or {},
        unit_hint=state.get("unit_hint") or "",
        errors=list(state.get("errors") or []),
    )
