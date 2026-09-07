"""Build executable pandas solutions from validated raw-table decisions."""
from __future__ import annotations

from typing import Sequence

import pandas as pd

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.solve.common.units import MONEY_SCALE, scale_expression
from finance_qa.modules.solve.solvers.raw_table_linking import render as _render
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawRatioDecision,
    RawTableLinkError,
)
from finance_qa.modules.solve.solvers.raw_table_linking.validate import (
    validate_decision,
    validate_ratio_decision,
)
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawCellCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)


def build_solution(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
    candidates: Sequence[RawCellCandidate],
    *,
    frame_loader=load_frame,
    scale_expression_func=scale_expression,
    validate_decision_func=validate_decision,
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawCellCandidate]]:
    chosen = validate_decision_func(request, decision, candidates)
    names: dict[str, str] = {}
    frames: dict[str, pd.DataFrame] = {}
    table_to_var: dict[str, str] = {}
    for candidate in chosen:
        if candidate.table_id not in table_to_var:
            var = f"df{len(table_to_var) + 1}"
            table_to_var[candidate.table_id] = var
            names[var] = candidate.table_id
            frames[var] = frame_loader(candidate.table_id)
    terms = [candidate.query(table_to_var[candidate.table_id], request.value_transform) for candidate in chosen]
    first = chosen[0]
    source_unit = first.source_unit
    if request.operation in {"diff", "sum", "avg"}:
        source_units = [candidate.source_unit for candidate in chosen]
        if (
            source_unit in MONEY_SCALE
            and all(unit in MONEY_SCALE for unit in source_units)
            and len(set(source_units)) > 1
        ):
            # Put additive terms in one money unit before executor-level scaling.
            terms = [
                scale_expression_func(term, candidate.source_unit, source_unit)
                for term, candidate in zip(terms, chosen, strict=True)
            ]
    if request.operation == "direct":
        query = terms[0]
    elif request.operation == "diff":
        query = f"{terms[0]} - {terms[1]}"
    elif request.operation == "sum":
        query = " + ".join(terms)
    elif request.operation == "avg":
        query = f"({' + '.join(terms)}) / {len(terms)}"
    elif request.operation == "ratio":
        query = f"({terms[0]}) / ({terms[1]})"
    else:  # pragma: no cover - Literal keeps this unreachable
        raise RawTableLinkError(f"unsupported operation {request.operation}")

    solution = PandasSolution(
        table_variable=table_to_var[first.table_id],
        target_row=str(first.row_position),
        target_column=first.column,
        source_unit=source_unit,
        target_unit=decision.target_unit if decision.target_unit != "unknown" else request.target_unit,
        pandas_query=query,
    )
    return solution, frames, names, chosen


def build_ratio_solution(
    request: RawLinkRequest,
    decision: RawRatioDecision,
    candidates: Sequence[RawLinkedCandidate],
    *,
    frame_loader=load_frame,
    validate_ratio_decision_func=validate_ratio_decision,
    candidate_table_ids_func=_render._candidate_table_ids,
    candidate_query_func=_render._candidate_query,
    candidate_first_cell_func=_render._candidate_first_cell,
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawLinkedCandidate]]:
    selections = validate_ratio_decision_func(request, decision, candidates)
    chosen = [candidate for _, numerator, denominator in selections for candidate in [*numerator, *denominator]]
    names: dict[str, str] = {}
    frames: dict[str, pd.DataFrame] = {}
    table_to_var: dict[str, str] = {}
    for candidate in chosen:
        for table_id in candidate_table_ids_func(candidate):
            if table_id not in table_to_var:
                var = f"df{len(table_to_var) + 1}"
                table_to_var[table_id] = var
                names[var] = table_id
                frames[var] = frame_loader(table_id)

    def side_expr(side: Sequence[RawLinkedCandidate]) -> str:
        terms = [candidate_query_func(candidate, table_to_var, request.value_transform) for candidate in side]
        if len(terms) == 1:
            return terms[0]
        return "(" + " + ".join(terms) + ")"

    ratio_terms: list[str] = []
    for _, numerator, denominator in selections:
        ratio_terms.append(f"({side_expr(numerator)}) / ({side_expr(denominator)})")
    if request.ratio_aggregate == "avg":
        query = f"({' + '.join(ratio_terms)}) / {len(ratio_terms)}"
    else:
        query = ratio_terms[0]
    target_unit = decision.target_unit if decision.target_unit != "unknown" else request.target_unit
    if target_unit == "percent":
        query = f"({query}) * 100"

    first_table_id, first_row, first_column, first_unit = candidate_first_cell_func(chosen[0])
    solution = PandasSolution(
        table_variable=table_to_var[first_table_id],
        target_row=str(first_row),
        target_column=first_column,
        source_unit=first_unit,  # type: ignore[arg-type]
        target_unit=target_unit,  # type: ignore[arg-type]
        pandas_query=query,
    )
    return solution, frames, names, chosen


__all__ = [
    "build_ratio_solution",
    "build_solution",
]
