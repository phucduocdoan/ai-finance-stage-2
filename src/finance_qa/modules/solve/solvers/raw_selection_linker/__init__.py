"""Raw-table selection over bounded cell candidates.

This capability covers selection questions whose facts live outside the
structured main-statement catalog: choose the year/company with the largest or
smallest raw-table metric, then return either that year/company's value or the
selected year. The model only chooses candidate ids from a bounded list; Python
validates scope/unit evidence and performs the argmax/argmin.

Facade: the implementation lives in the `selection_request`, `selection_candidates`,
`selection_decision` and `year_selection` submodules. This module re-exports their
public names and holds the orchestration that ties them together, so existing
imports of `finance_qa.modules.solve.solvers.raw_selection_linker` keep working
unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from finance_qa.modules.solve.solvers import raw_table_linker as raw
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_candidates import (
    _candidate_first_cell,
    _component_phrases,
    _exclude_phrase_hits,
    _is_flow_candidate,
    _is_total_candidate,
    _phrase_match_score,
    _ranking_value,
    _requires_component_sum,
    _row_phrase_group_candidates,
    _same_selector_unit_kind,
)
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_decision import (
    RAW_SELECTION_SYSTEM,
    RawSelectionDecision,
    RawSelectionError,
    RawSelectionSlotDecision,
    _can_reuse_selector_as_answer,
    aplan_raw_selection,
    decision_from_flow_top_candidates,
    decision_from_row_groups,
    decision_from_semantic_plan,
    validate_decision,
)
from finance_qa.modules.solve.solvers.raw_selection_linker.selection_request import (
    SelectionAnswerKind,
    SelectionAxis,
    SelectionOrder,
    build_request,
)
from finance_qa.modules.solve.solvers.raw_selection_linker.year_selection import (
    build_solution,
    year_selection_query,
)
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)
from finance_qa.modules.tools.python_exec import run_query


@dataclass
class _SelectionExpansion:
    """Candidates after search-plan expansion and component-row-group augmentation."""

    search_plan: raw.RawSearchPlan | None
    request: RawLinkRequest
    candidates: Sequence[RawLinkedCandidate]
    row_groups: list[RawGroupCandidate]
    solution_candidates: list[RawLinkedCandidate]
    solution_cand_diag: dict[str, Any]


async def _expand_selection_with_search_plan(
    state: Mapping[str, Any],
    request: RawLinkRequest,
    candidates: Sequence[RawLinkedCandidate],
    cand_diag: dict[str, Any],
    *,
    planner_thinking: bool,
) -> _SelectionExpansion:
    search_plan = await raw.aplan_raw_search(
        question=str(state.get("question") or ""),
        request=request,
        table_ids=list(state.get("table_ids") or []),
        shortlist=list(state.get("shortlist") or []),
        planner_thinking=planner_thinking,
    )
    expanded_request = raw.request_with_search_plan(request, search_plan)
    expanded_candidates, expanded_cand_diag = (
        (candidates, cand_diag)
        if expanded_request == request
        else raw.build_candidates(
            expanded_request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            limit_per_slot=32,
        )
    )
    row_groups, row_group_diag = _row_phrase_group_candidates(
        expanded_request,
        search_plan if search_plan and search_plan.supported else None,
        expanded_candidates,
    )
    solution_candidates: list[RawLinkedCandidate] = [*expanded_candidates, *row_groups]
    solution_cand_diag = {
        **expanded_cand_diag,
        "candidate_count": len(solution_candidates),
        "row_group_summary": row_group_diag,
    }
    return _SelectionExpansion(
        search_plan=search_plan,
        request=expanded_request,
        candidates=expanded_candidates,
        row_groups=row_groups,
        solution_candidates=solution_candidates,
        solution_cand_diag=solution_cand_diag,
    )


@dataclass
class _SelectionDecisionResult:
    """Outcome of the row-group / flow / semantic / planner decision cascade."""

    semantic_plan: raw.RawSemanticPlan | None
    semantic_decision: RawSelectionDecision | None
    group_decision: RawSelectionDecision
    flow_decision: RawSelectionDecision
    decision_source: str
    decision: RawSelectionDecision


async def _selection_decision_cascade(
    state: Mapping[str, Any],
    request: RawLinkRequest,
    expansion: _SelectionExpansion,
    *,
    order: SelectionOrder,
    answer_kind: SelectionAnswerKind,
    planner_thinking: bool,
) -> _SelectionDecisionResult:
    solution_request = expansion.request
    search_plan = expansion.search_plan
    question = str(state.get("question") or "")

    semantic_plan = (
        raw.semantic_plan_from_search_plan(solution_request, search_plan)
        if search_plan and search_plan.supported
        else None
    )
    semantic_decision = (
        decision_from_semantic_plan(
            solution_request,
            semantic_plan,
            expansion.candidates,
            order=order,
            answer_kind=answer_kind,
            question=question,
        )
        if semantic_plan
        else None
    )
    component_group_required = bool(
        search_plan and search_plan.supported and _requires_component_sum(search_plan, solution_request)
    )
    group_decision = decision_from_row_groups(
        solution_request,
        expansion.row_groups,
        order=order,
        answer_kind=answer_kind,
        question=question,
        target_unit=search_plan.target_unit if search_plan and search_plan.supported else solution_request.target_unit,
    )
    if component_group_required and not group_decision.supported:
        raise RawSelectionError(group_decision.reason or "component row groups are not deterministic")
    flow_decision = decision_from_flow_top_candidates(
        solution_request,
        expansion.candidates,
        order=order,
        answer_kind=answer_kind,
        question=question,
        target_unit=request.target_unit if request.target_unit != "unknown" else solution_request.target_unit,
    )
    decision_source = (
        "row_group_deterministic"
        if group_decision.supported
        else "flow_top_deterministic"
        if flow_decision.supported
        else "semantic_constraints"
        if semantic_decision and semantic_decision.supported
        else "selection_planner"
    )
    decision = (
        group_decision
        if group_decision.supported
        else flow_decision
        if flow_decision.supported
        else semantic_decision
    )
    if decision is None or not decision.supported:
        decision = await aplan_raw_selection(
            question=question,
            request=solution_request,
            order=order,
            answer_kind=answer_kind,
            candidates=expansion.solution_candidates,
            planner_thinking=planner_thinking,
        )
    return _SelectionDecisionResult(
        semantic_plan=semantic_plan,
        semantic_decision=semantic_decision,
        group_decision=group_decision,
        flow_decision=flow_decision,
        decision_source=decision_source,
        decision=decision,
    )


async def aprepare_raw_selection_linker(
    state: Mapping[str, Any],
    *,
    use_planner: bool = True,
    planner_thinking: bool = False,
) -> dict[str, Any]:
    """Prepare a validated raw-table selection answer for graph execution."""
    request, axis, order, answer_kind, reason = build_request(state)
    if request is None or axis is None or order is None or answer_kind is None:
        raise RawSelectionError(reason)

    candidates, cand_diag = raw.build_candidates(
        request,
        table_ids=list(state.get("table_ids") or []),
        shortlist=list(state.get("shortlist") or []),
        limit_per_slot=32,
    )
    if not candidates:
        raise RawSelectionError("no raw selection candidates")
    if cand_diag["missing_slots"]:
        raise RawSelectionError(f"missing candidates for slots {cand_diag['missing_slots']}")
    if not use_planner:
        raise RawSelectionError("raw selection requires planner")

    expansion = await _expand_selection_with_search_plan(
        state, request, candidates, cand_diag, planner_thinking=planner_thinking,
    )
    solution_request = expansion.request
    search_plan = expansion.search_plan

    cascade = await _selection_decision_cascade(
        state, request, expansion, order=order, answer_kind=answer_kind, planner_thinking=planner_thinking,
    )

    allow_total_row_selector = solution_request.wants_total
    if search_plan and search_plan.supported and not search_plan.prefer_total_row:
        allow_total_row_selector = False
    solution, frames, names, chosen, winning_slot = build_solution(
        solution_request,
        cascade.decision,
        expansion.solution_candidates,
        expected_order=order,
        expected_answer_kind=answer_kind,
        allow_total_row_selector=allow_total_row_selector,
    )
    return {
        "solution": solution,
        "frames": frames,
        "names": names,
        "table_ids": list(dict.fromkeys(table_id for candidate in chosen for table_id in raw._candidate_table_ids(candidate))),
        "diag": {
            "done": True,
            "axis": axis,
            "order": order,
            "answer_kind": answer_kind,
            "winning_slot": winning_slot.key,
            "initial_request": request.model_dump(),
            "request": solution_request.model_dump(),
            "initial_candidate_summary": cand_diag,
            "candidate_summary": expansion.solution_cand_diag,
            "search_plan": search_plan.model_dump() if search_plan else None,
            "search_expansion_used": solution_request != request,
            "semantic_plan": cascade.semantic_plan.model_dump() if cascade.semantic_plan else None,
            "semantic_decision": cascade.semantic_decision.model_dump() if cascade.semantic_decision else None,
            "row_group_decision": cascade.group_decision.model_dump(),
            "flow_decision": cascade.flow_decision.model_dump(),
            "decision_source": cascade.decision_source,
            "decision": cascade.decision.model_dump(),
            "chosen": [candidate.model_dump() for candidate in chosen],
        },
    }


def should_attempt_raw_selection_linker(state: Mapping[str, Any]) -> tuple[bool, str]:
    request, axis, order, answer_kind, reason = build_request(state)
    return (request is not None and axis is not None and order is not None and answer_kind is not None), reason


__all__ = [
    "RawSelectionDecision",
    "RawSelectionError",
    "RawSelectionSlotDecision",
    "aplan_raw_selection",
    "aprepare_raw_selection_linker",
    "build_request",
    "build_solution",
    "decision_from_flow_top_candidates",
    "decision_from_row_groups",
    "should_attempt_raw_selection_linker",
    "validate_decision",
]
