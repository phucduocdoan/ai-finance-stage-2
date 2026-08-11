"""Public code generation service."""
from __future__ import annotations

from typing import Any

from finance_qa.modules.codegen.generator import generate
from finance_qa.modules.codegen.formula import solve_formula
from finance_qa.modules.codegen.repl import solve_repl


def generate_solution(
    question: str,
    table_ids: list[str],
    *,
    thinking: bool = False,
    use_planner: bool = True,
    fallback: bool = True,
) -> dict[str, Any]:
    """Generate pandas code and answer for a question over selected tables."""
    return generate(
        question,
        table_ids,
        thinking=thinking,
        use_planner=use_planner,
        fallback=fallback,
    )


def generate_lookup_solution(question: str, table_ids: list[str]) -> dict[str, Any]:
    """Planner-only single-cell lookup generation used by the graph lookup solver."""
    return generate_solution(question, table_ids, use_planner=True, fallback=False)


def generate_formula_solution(
    *,
    question: str,
    frames: dict[str, Any],
    names: dict[str, str],
    tickers: list[str] | None = None,
    years: list[int] | None = None,
    unit_hint: str | None = None,
    errors: list[str] | None = None,
    thinking: bool = True,
    max_tokens: int = 8192,
) -> dict[str, Any]:
    """Canonical formula planning/execution used by the graph formula solver."""
    return solve_formula(
        question=question,
        frames=frames,
        names=names,
        tickers=tickers,
        years=years,
        unit_hint=unit_hint,
        errors=errors,
        thinking=thinking,
        max_tokens=max_tokens,
    )


def generate_repl_solution(
    *,
    question: str,
    frames: dict[str, Any],
    names: dict[str, str],
    unit_hint: str = "",
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Tool-calling REPL solution used by the graph fallback solver."""
    return solve_repl(
        question=question,
        frames=frames,
        names=names,
        unit_hint=unit_hint,
        errors=errors,
    )
