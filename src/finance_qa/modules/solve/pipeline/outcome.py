"""Shared solver outcome helpers.

Graph nodes still return LangGraph state updates, but every solver diag should
carry the same small contract so routing and debugging do not depend on ad hoc
shape checks.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping, TypedDict


SolverStatus = Literal["done", "declined", "error"]


class SolverOutcome(TypedDict, total=False):
    """Diagnostic contract stored at ``diag[solver_name]``."""

    status: SolverStatus
    done: bool
    reason: str


def with_status(
    payload: Mapping[str, Any] | None,
    status: SolverStatus,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Return a diag payload with normalized ``status``/``done`` fields."""
    out = dict(payload or {})
    out["status"] = status
    out["done"] = status == "done"
    if reason or not isinstance(out.get("reason"), str):
        out["reason"] = reason
    return out


def solver_done(state: Mapping[str, Any], solver: str) -> bool:
    """Whether a solver diag says the solver answered the question."""
    diag = (state.get("diag") or {}).get(solver, {})
    return diag.get("status") == "done" or bool(diag.get("done"))


def solver_update(
    state: Mapping[str, Any],
    solver: str,
    payload: Mapping[str, Any] | None,
    *,
    status: SolverStatus,
    reason: str = "",
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Build a state update that records one solver outcome."""
    update: dict[str, Any] = {
        "diag": {
            **(state.get("diag") or {}),
            solver: with_status(payload, status, reason=reason),
        },
    }
    if errors is not None:
        update["errors"] = list(state.get("errors") or []) + errors
    return update


def append_unique(existing: list[Any] | None, additions: list[Any] | None) -> list[Any]:
    """Append items while preserving first-seen order."""
    out = list(existing or [])
    for item in additions or []:
        if item not in out:
            out.append(item)
    return out


def declined(
    state: Mapping[str, Any],
    solver: str,
    reason: str,
    *,
    payload: Mapping[str, Any] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """State update for a solver that safely declined the question."""
    return solver_update(
        state, solver, payload, status="declined", reason=reason, errors=errors
    )


def errored(
    state: Mapping[str, Any],
    solver: str,
    reason: str,
    *,
    payload: Mapping[str, Any] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """State update for a solver that hit an unexpected error."""
    return solver_update(
        state, solver, payload, status="error", reason=reason, errors=errors
    )


def done_payload(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Diag payload for a solver that answered."""
    return with_status(payload, "done")


def answered(
    state: Mapping[str, Any],
    solver: str,
    *,
    answer: float,
    pandas_query: str,
    evidence: list[dict[str, Any]],
    table_ids: list[str],
    diag_payload: Mapping[str, Any] | None = None,
    errors: list[str] | None = None,
    frames: Mapping[str, Any] | None = None,
    names: Mapping[str, str] | None = None,
    evidence_tables: list[str] | None = None,
    codegen_prompt: str | None = None,
    solution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """State update for a solver that directly answered the question."""
    update: dict[str, Any] = {
        "answer": float(answer),
        "pandas_query": pandas_query,
        "evidence": list(evidence),
        "table_ids": list(table_ids),
        "solver": solver,
        "errors": list(errors if errors is not None else state.get("errors") or []),
        "diag": {
            **(state.get("diag") or {}),
            solver: done_payload(diag_payload),
        },
    }
    if frames is not None:
        update["frames"] = dict(frames)
    if names is not None:
        update["names"] = dict(names)
    if evidence_tables is not None:
        update["evidence_tables"] = list(evidence_tables)
    if codegen_prompt is not None:
        update["codegen_prompt"] = codegen_prompt
    if solution is not None:
        update["solution"] = dict(solution)
    return update


__all__ = [
    "SolverOutcome",
    "SolverStatus",
    "answered",
    "append_unique",
    "declined",
    "done_payload",
    "errored",
    "solver_done",
    "solver_update",
    "with_status",
]
