"""Capability trace for the finance solve graph.

This module is deliberately diagnostic: it mirrors the graph's current
fail-closed solver order without deciding answers or replacing solver guards.
The goal is to make routing auditable by executable capability, not by the
six evaluation labels.
"""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.modules.solve.solvers.cell_locator import build_request
from finance_qa.modules.solve.solvers.decompose import axis_of
from finance_qa.modules.solve.solvers.formula_facts import (
    deterministic_formula_plan,
    should_attempt_formula_facts,
)
from finance_qa.modules.solve.solvers.raw_selection_linker import should_attempt_raw_selection_linker
from finance_qa.modules.solve.solvers.raw_table_linker import should_attempt_raw_table_linker
from finance_qa.modules.solve.solvers.selection_facts import should_attempt_selection_facts


def capability_trace(
    state: Mapping[str, Any],
    *,
    cell_locator: bool = False,
    formula_facts: bool = False,
    raw_table_linker: bool = False,
    selection_facts: bool = False,
    raw_selection_linker: bool = False,
    structured_facts: bool = False,
    selection_decompose: bool = False,
) -> dict[str, Any]:
    """Return a cheap, side-effect-free trace of solver capabilities.

    The trace answers "which branch is allowed to try, and why?". It does not
    inspect table contents and does not promise fact coverage; actual solvers
    still own their deeper validation and fallback behavior.
    """
    decisions = {
        "cell_locator": _cell_locator_decision(state, enabled=cell_locator),
        "formula_facts": _formula_facts_decision(state, enabled=formula_facts),
        "raw_table_linker": _raw_table_linker_decision(
            state, enabled=raw_table_linker,
        ),
        "selection_facts": _selection_facts_decision(
            state, enabled=selection_facts,
        ),
        "raw_selection_linker": _raw_selection_linker_decision(
            state, enabled=raw_selection_linker,
        ),
        "structured_facts": _structured_facts_decision(enabled=structured_facts),
        "selection_decompose": _selection_decision(
            state, enabled=selection_decompose,
        ),
        "codegen": {
            "enabled": True,
            "attempt": True,
            "reason": "fallback",
        },
    }
    return {
        "routing_basis": "capability",
        "order": [
            name for name in (
                "cell_locator",
                "formula_facts",
                "raw_table_linker",
                "selection_facts",
                "raw_selection_linker",
                "structured_facts",
                "selection_decompose",
                "codegen",
            )
            if decisions[name]["enabled"]
        ],
        "decisions": decisions,
    }


def _cell_locator_decision(
    state: Mapping[str, Any], *, enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    request, reason = build_request(state)
    if request is None:
        return {"enabled": True, "attempt": False, "reason": reason}
    return {
        "enabled": True,
        "attempt": True,
        "reason": "",
        "request": request.model_dump(),
    }


def _formula_facts_decision(
    state: Mapping[str, Any], *, enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    attempt, reason = should_attempt_formula_facts(dict(state))
    if not attempt:
        return {"enabled": True, "attempt": False, "reason": reason}

    plan = deterministic_formula_plan(dict(state))
    out: dict[str, Any] = {
        "enabled": True,
        "attempt": True,
        "reason": "",
        "deterministic": bool(plan.supported),
    }
    if plan.supported:
        out["plan"] = {
            "operation": plan.operation,
            "tickers": plan.tickers,
            "years": plan.years,
            "doc_type": plan.doc_type,
            "answer_metric": plan.answer_metric,
            "target_unit": plan.target_unit,
        }
    else:
        out["planner_fallback"] = True
        out["planner_reason"] = plan.reason or "needs bounded planner"
    return out


def _raw_table_linker_decision(
    state: Mapping[str, Any], *, enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    attempt, reason = should_attempt_raw_table_linker(state)
    if not attempt:
        return {"enabled": True, "attempt": False, "reason": reason}
    return {"enabled": True, "attempt": True, "reason": ""}


def _selection_facts_decision(
    state: Mapping[str, Any], *, enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    attempt, reason = should_attempt_selection_facts(state)
    if not attempt:
        return {"enabled": True, "attempt": False, "reason": reason}
    return {"enabled": True, "attempt": True, "reason": ""}


def _raw_selection_linker_decision(
    state: Mapping[str, Any], *, enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    attempt, reason = should_attempt_raw_selection_linker(state)
    if not attempt:
        return {"enabled": True, "attempt": False, "reason": reason}
    return {"enabled": True, "attempt": True, "reason": ""}


def _structured_facts_decision(*, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    return {
        "enabled": True,
        "attempt": True,
        "reason": "planner-gated main-statement selection",
    }


def _selection_decision(
    state: Mapping[str, Any], *, enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "attempt": False, "reason": "disabled"}
    axis = axis_of(
        str(state.get("question") or ""),
        list(state.get("years") or []),
        list(state.get("tickers") or []),
    )
    if axis is None:
        return {"enabled": True, "attempt": False, "reason": "no selection axis"}
    axis_name, elements = axis
    return {
        "enabled": True,
        "attempt": True,
        "reason": "",
        "axis": axis_name,
        "elements": [str(element) for element in elements],
    }


__all__ = ["capability_trace"]
