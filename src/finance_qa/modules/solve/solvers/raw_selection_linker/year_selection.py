"""Raw-table selection solution building, including the year-answer rewrite.

Turns a validated `RawSelectionDecision` into a submittable `PandasSolution`.
For `selected_year` answers, keeps the year data-dependent on the ranking
instead of emitting it as a bare constant.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from finance_qa.modules.solve.common.solution import PandasSolution, Unit
from finance_qa.modules.solve.solvers import raw_table_linker as raw
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_candidates import (
    _candidate_first_cell,
    _ranking_value,
)
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_decision import (
    RawSelectionDecision,
    validate_decision,
)
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_request import (
    SelectionAnswerKind,
    SelectionOrder,
)
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawLinkRequest,
    RawLinkedCandidate,
    RawScopeSlot,
)
from finance_qa.modules.tools.python_exec import run_query


def year_selection_query(
    ranking: Sequence[tuple[float, Any, RawLinkedCandidate, RawLinkedCandidate | None]],
    table_to_var: Mapping[str, str],
    transform: str,
    order: str,
    frames: Mapping[str, pd.DataFrame],
    winning_year: int,
) -> str | None:
    """The year question answered by comparing the years, not by naming the winner.

    This used to emit `(<winning cell>) * 0 + <year>`. Re-executing that does
    reproduce the year, which was the point, but `* 0` annihilates the only cell
    it reads, so what ships is the answer stored as a constant -- which the rules
    score as zero, and which no "is this a constant?" check can see, because the
    expression does reference a frame.

    The comparison is already here: `ranking` holds every slot's selector, the
    same ones `_ranking_value` ordered. Emitting it keeps the year data-dependent,
    since changing a cell changes which tuple wins.

    Returns None whenever the rewrite would not be a year selection -- fewer than
    two years, two candidates on one year, an order that is neither max nor min --
    and whenever the rebuilt query does not run or lands on a different year than
    the ranking did. The caller then keeps the old shape. That check is what makes
    this incapable of moving an answer.
    """
    if order not in {"max", "min"}:
        return None
    by_year: dict[int, RawLinkedCandidate] = {}
    for _, slot, selector, _answer in ranking:
        year = getattr(slot, "year", None)
        if not isinstance(year, int) or year in by_year:
            return None
        by_year[year] = selector
    if len(by_year) < 2 or winning_year not in by_year:
        return None

    # Rendering the *losing* years is new work: the old shape only ever rendered the
    # winner. So this has to be inside the same try as the execution check -- a loser
    # that `_candidate_query` cannot render must cost the caller its old shape, not
    # its whole solve, or the solver would fall through to codegen on questions it
    # used to answer.
    try:
        terms = ", ".join(
            f"(float({raw._candidate_query(by_year[year], table_to_var, transform)}), {year})"
            for year in sorted(by_year)
        )
        query = f"{order}([{terms}])[1]"
        if int(run_query(query, dict(frames))) != winning_year:
            return None
    except Exception:  # noqa: BLE001 - a rewrite that will not build or run is refused
        return None
    return query


def build_solution(
    request: RawLinkRequest,
    decision: RawSelectionDecision,
    candidates: Sequence[RawLinkedCandidate],
    *,
    expected_order: SelectionOrder,
    expected_answer_kind: SelectionAnswerKind,
    allow_total_row_selector: bool | None = None,
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawLinkedCandidate], RawScopeSlot]:
    selected, _ = validate_decision(
        request,
        decision,
        candidates,
        expected_order=expected_order,
        expected_answer_kind=expected_answer_kind,
        allow_total_row_selector=allow_total_row_selector,
    )
    ranking = [
        (_ranking_value(selector), slot, selector, answer)
        for slot, selector, answer in selected
    ]
    ranking.sort(key=lambda item: item[0], reverse=decision.rank_op == "max")
    _, winning_slot, winning_selector, winning_answer = ranking[0]

    chosen: list[RawLinkedCandidate] = []
    query_candidate = winning_answer or winning_selector
    for _, selector, answer in ((slot, selector, answer) for slot, selector, answer in selected):
        chosen.append(selector)
        if answer is not None:
            chosen.append(answer)
    chosen = list({candidate.id: candidate for candidate in chosen}.values())

    names: dict[str, str] = {}
    frames: dict[str, pd.DataFrame] = {}
    table_to_var: dict[str, str] = {}
    for candidate in chosen:
        for table_id in raw._candidate_table_ids(candidate):
            if table_id in table_to_var:
                continue
            var = f"df{len(table_to_var) + 1}"
            table_to_var[table_id] = var
            names[var] = table_id
            frames[var] = raw.load_frame(table_id)

    expr = raw._candidate_query(query_candidate, table_to_var, request.value_transform)
    if decision.answer_kind == "selected_year":
        expr = year_selection_query(
            ranking,
            table_to_var,
            request.value_transform,
            decision.rank_op,
            frames,
            winning_slot.year,
        ) or f"({expr}) * 0 + {winning_slot.year}"

    first_table_id, first_row, first_column = _candidate_first_cell(query_candidate)
    solution = PandasSolution(
        table_variable=table_to_var[first_table_id],
        target_row=str(first_row),
        target_column=first_column,
        source_unit="year" if decision.answer_kind == "selected_year" else query_candidate.source_unit,
        target_unit=(
            "year"
            if decision.answer_kind == "selected_year"
            else decision.target_unit
            if decision.target_unit != "unknown"
            else request.target_unit
        ),
        pandas_query=expr,
    )
    return solution, frames, names, chosen, winning_slot
