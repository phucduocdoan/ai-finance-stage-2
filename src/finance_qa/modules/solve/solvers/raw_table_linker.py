"""Raw-table cell linker for fixed-scope arithmetic.

``long_format`` is a clean main-statement fact layer. This module covers the
next controlled slice: questions whose scope is already fixed, but whose facts
live in raw CSV tables, notes, bank layouts, or tables without VAS ``Mã số``.

The LLM does not write pandas. It only chooses from a bounded list of real cell
candidates and an operation. Python validates scope/unit/ambiguity and builds the
submitted expression.

This module is a facade: nearly every name below is a thin delegate or bare
re-export of the real implementation in `raw_table_linking/*`. It exists so
callers get one flat import surface instead of reaching into 10 submodules.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import pandas as pd

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.context import meta_for, page_text, table_metadata
from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.lookup import label_column
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, PandasSolution, Unit
from finance_qa.modules.solve.common.units import scale_expression
from finance_qa.modules.solve.facts.table_profile import build_table_profile
from finance_qa.modules.solve.solvers.raw_table_linking import candidates as _candidates
from finance_qa.modules.solve.solvers.raw_table_linking import decision as _decision
from finance_qa.modules.solve.solvers.raw_table_linking import planner as _planner
from finance_qa.modules.solve.solvers.raw_table_linking import prepare as _prepare
from finance_qa.modules.solve.solvers.raw_table_linking import ratio_options as _ratio_options
from finance_qa.modules.solve.solvers.raw_table_linking import request as _request
from finance_qa.modules.solve.solvers.raw_table_linking import render as _render
from finance_qa.modules.solve.solvers.raw_table_linking import scoring as _scoring
from finance_qa.modules.solve.solvers.raw_table_linking import solution as _solution
from finance_qa.modules.solve.solvers.raw_table_linking import validate as _validate
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawRatioDecision,
    RawRatioOption,
    RawRatioOptionDecision,
    RawRatioOptionSlotDecision,
    RawRatioSlotDecision,
    RawSearchPlan,
    RawSemanticPlan,
    RawSlotSemanticConstraint,
    RawTableLinkError,
)
from finance_qa.modules.solve.solvers.table_profiles.schema import (
    RawCellCandidate,
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
    RawOperation,
    RawScopeSlot,
)


_MIN_DIRECT_SCORE = 0.84
_NORMALIZED_UNSUPPORTED_REASON = "complete candidate_ids supplied despite unsupported:"


_YEAR = _scoring._YEAR
_CURRENT_COL = _scoring._CURRENT_COL
_PRIOR_COL = _scoring._PRIOR_COL
_FLOW_QUESTION = _scoring._FLOW_QUESTION
_FLOW_COL = _scoring._FLOW_COL
_BALANCE_COL = _scoring._BALANCE_COL
_MONEY_UNITS = _scoring._MONEY_UNITS
_text = _scoring._text
_tokens = _request._tokens
_wants_total = _request._wants_total
_text_list = _scoring._text_list
_token_score = _scoring._token_score
_semantic_score = _scoring._semantic_score
_rank_bonus = _scoring._rank_bonus
_labels_a_row = _scoring._labels_a_row
_row_text = _scoring._row_text
_is_total_row = _scoring._is_total_row
_component_role_from_text = _scoring._component_role_from_text
_is_generic_period_row = _scoring._is_generic_period_row
_generic_period_row_score = _scoring._generic_period_row_score
_row_period_adjustment = _scoring._row_period_adjustment
_is_component_row = _scoring._is_component_row
_is_percent_column = _scoring._is_percent_column
_leaf = _scoring._leaf
_column_score = _scoring._column_score
_flow_column_adjustment = _scoring._flow_column_adjustment
_safe_number = _scoring._safe_number
_row_has_numeric_value = _scoring._row_has_numeric_value
_format_value = _scoring._format_value
_table_context = _scoring._table_context
_short_context = _scoring._short_context
_page_context_hint = _scoring._page_context_hint


def _scope_ok(table_id: str, slot: RawScopeSlot, doc_type: str) -> bool:
    return _request._scope_ok(table_id, slot, doc_type, meta_lookup=meta_for)


def _scope_table_ids(slot: RawScopeSlot, doc_type: str) -> list[str]:
    return _request._scope_table_ids(slot, doc_type, metadata_lookup=table_metadata)


def _scope_identity_tokens(slots: Sequence[RawScopeSlot], doc_type: str) -> list[str]:
    return _request._scope_identity_tokens(
        slots,
        doc_type,
        meta_lookup=meta_for,
        metadata_lookup=table_metadata,
    )


def build_request(state: Mapping[str, Any]) -> tuple[RawLinkRequest | None, str]:
    return _request.build_request(
        state,
        meta_lookup=meta_for,
        metadata_lookup=table_metadata,
    )


def should_attempt_raw_table_linker(state: Mapping[str, Any]) -> tuple[bool, str]:
    return _request.should_attempt_raw_table_linker(
        state,
        meta_lookup=meta_for,
        metadata_lookup=table_metadata,
    )


def _scoring_query_for_table(request: RawLinkRequest, table_id: str) -> tuple[list[str], str]:
    return _scoring._scoring_query_for_table(request, table_id, meta_lookup=meta_for)


def _column_year(column: object, table_id: str, meta_year: object) -> int | None:
    return _scoring._column_year(column, table_id, meta_year, frame_loader=load_frame)


def _candidate_rows(
    request: RawLinkRequest,
    slot: RawScopeSlot,
    table_id: str,
    ranked: Sequence[str],
    *,
    start_id: int,
) -> list[RawCellCandidate]:
    return _candidates._candidate_rows(
        request,
        slot,
        table_id,
        ranked,
        start_id=start_id,
        frame_loader=load_frame,
        meta_lookup=meta_for,
        page_text_lookup=page_text,
    )


def build_candidates(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    limit_per_slot: int = 12,
    max_tables: int = 140,
) -> tuple[list[RawCellCandidate], dict[str, Any]]:
    return _candidates.build_candidates(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        limit_per_slot=limit_per_slot,
        max_tables=max_tables,
        frame_loader=load_frame,
        meta_lookup=meta_for,
        page_text_lookup=page_text,
        metadata_lookup=table_metadata,
    )


_group_role_score = _candidates._group_role_score
_score_group_candidate = _candidates._score_group_candidate


def build_ratio_candidates(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    cell_limit_per_slot: int = 32,
    group_limit_per_slot: int = 18,
    max_tables: int = 140,
) -> tuple[list[RawLinkedCandidate], dict[str, Any]]:
    return _candidates.build_ratio_candidates(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        cell_limit_per_slot=cell_limit_per_slot,
        group_limit_per_slot=group_limit_per_slot,
        max_tables=max_tables,
        frame_loader=load_frame,
        meta_lookup=meta_for,
        page_text_lookup=page_text,
        metadata_lookup=table_metadata,
    )


_ratio_numerator_roles = _candidates._ratio_numerator_roles


def _ratio_side_for_candidate(request: RawLinkRequest, candidate: RawLinkedCandidate) -> set[str]:
    return _ratio_options._ratio_side_for_candidate(request, candidate)


def _ratio_option_label(candidate: RawLinkedCandidate) -> str:
    return _ratio_options._ratio_option_label(candidate)


def _candidate_context(candidate: RawLinkedCandidate) -> str:
    return _ratio_options._candidate_context(candidate)


def _ratio_option_period_rank(request: RawLinkRequest, candidate: RawLinkedCandidate) -> int:
    return _ratio_options._ratio_option_period_rank(request, candidate)


def _ratio_option_column_score(candidate: RawLinkedCandidate) -> float:
    return _ratio_options._ratio_option_column_score(candidate)


def _ratio_option_table_score(candidate: RawLinkedCandidate) -> float:
    return _ratio_options._ratio_option_table_score(candidate)


def _ratio_option_evidence_rank(
    request: RawLinkRequest,
    candidate: RawLinkedCandidate,
    side: str,
) -> int:
    return _ratio_options._ratio_option_evidence_rank(request, candidate, side)


def build_ratio_options(
    request: RawLinkRequest,
    candidates: Sequence[RawLinkedCandidate],
    *,
    max_options_per_side: int = 8,
) -> tuple[list[RawRatioOption], dict[str, Any]]:
    return _ratio_options.build_ratio_options(
        request,
        candidates,
        max_options_per_side=max_options_per_side,
    )


def render_ratio_options(
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
) -> str:
    return _render.render_ratio_options(request, options)


def deterministic_ratio_option_decision(
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
) -> RawRatioOptionDecision:
    return _ratio_options.deterministic_ratio_option_decision(request, options)


def _prefer_ratio_option_surface(request: RawLinkRequest) -> bool:
    return _ratio_options._prefer_ratio_option_surface(request)


def _candidate_table_ids(candidate: RawLinkedCandidate) -> list[str]:
    return _render._candidate_table_ids(candidate)


def _candidate_query(
    candidate: RawLinkedCandidate,
    table_to_var: Mapping[str, str],
    transform: str,
) -> str:
    return _render._candidate_query(candidate, table_to_var, transform)


def _candidate_first_cell(candidate: RawLinkedCandidate) -> tuple[str, int, str, str]:
    return _render._candidate_first_cell(candidate)


def render_candidates(request: RawLinkRequest, candidates: Sequence[RawLinkedCandidate]) -> str:
    return _render.render_candidates(request, candidates)


def _dedupe_texts(values: Sequence[object], *, limit: int) -> list[str]:
    return _render._dedupe_texts(values, limit=limit)


def _table_label_snippets(
    request: RawLinkRequest,
    table_id: str,
    df: pd.DataFrame,
    profile_labels: Sequence[str],
    *,
    limit: int,
) -> list[str]:
    return _render._table_label_snippets(
        request,
        table_id,
        df,
        profile_labels,
        limit=limit,
        meta_lookup=meta_for,
        label_lookup=label_column,
    )


def render_table_contexts(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    limit_per_slot: int = 24,
    labels_per_table: int = 8,
    max_tables: int = 140,
) -> str:
    return _render.render_table_contexts(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        limit_per_slot=limit_per_slot,
        labels_per_table=labels_per_table,
        max_tables=max_tables,
        frame_loader=load_frame,
        meta_lookup=meta_for,
        metadata_lookup=table_metadata,
        label_lookup=label_column,
        profile_builder=build_table_profile,
    )


RAW_LINKER_SYSTEM = _planner.RAW_LINKER_SYSTEM


RAW_RATIO_LINKER_SYSTEM = _planner.RAW_RATIO_LINKER_SYSTEM


RAW_RATIO_OPTION_SYSTEM = _planner.RAW_RATIO_OPTION_SYSTEM


async def aplan_raw_table_linker(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
) -> RawLinkerDecision:
    return await _planner.aplan_raw_table_linker(
        question=question,
        request=request,
        candidates=candidates,
        planner_thinking=planner_thinking,
        chat_model_factory=get_chat_model,
        structured_method=STRUCTURED_METHOD,
        render_candidates_func=render_candidates,
    )


async def aplan_raw_ratio_options(
    *,
    question: str,
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
    planner_thinking: bool = False,
) -> RawRatioOptionDecision:
    return await _planner.aplan_raw_ratio_options(
        question=question,
        request=request,
        options=options,
        planner_thinking=planner_thinking,
        chat_model_factory=get_chat_model,
        structured_method=STRUCTURED_METHOD,
        render_ratio_options_func=render_ratio_options,
    )


async def aplan_raw_ratio_linker(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawLinkedCandidate],
    planner_thinking: bool = False,
) -> RawRatioDecision:
    return await _planner.aplan_raw_ratio_linker(
        question=question,
        request=request,
        candidates=candidates,
        planner_thinking=planner_thinking,
        chat_model_factory=get_chat_model,
        structured_method=STRUCTURED_METHOD,
        render_candidates_func=render_candidates,
    )



RAW_SEMANTIC_SYSTEM = _planner.RAW_SEMANTIC_SYSTEM


RAW_SEARCH_SYSTEM = _planner.RAW_SEARCH_SYSTEM


async def aplan_raw_search(
    *,
    question: str,
    request: RawLinkRequest,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    planner_thinking: bool = False,
) -> RawSearchPlan:
    return await _planner.aplan_raw_search(
        question=question,
        request=request,
        table_ids=table_ids,
        shortlist=shortlist,
        planner_thinking=planner_thinking,
        chat_model_factory=get_chat_model,
        structured_method=STRUCTURED_METHOD,
        render_table_contexts_func=render_table_contexts,
    )


def request_with_search_plan(request: RawLinkRequest, plan: RawSearchPlan | None) -> RawLinkRequest:
    return _planner.request_with_search_plan(
        request,
        plan,
        normalizer=_norm,
        tokenizer=_tokens,
    )


def semantic_plan_from_search_plan(request: RawLinkRequest, plan: RawSearchPlan) -> RawSemanticPlan:
    return _planner.semantic_plan_from_search_plan(request, plan)


async def aplan_raw_semantics(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
) -> RawSemanticPlan:
    return await _planner.aplan_raw_semantics(
        question=question,
        request=request,
        candidates=candidates,
        planner_thinking=planner_thinking,
        chat_model_factory=get_chat_model,
        structured_method=STRUCTURED_METHOD,
        render_candidates_func=render_candidates,
    )


_candidate_semantic_text = _decision._candidate_semantic_text
_candidate_row_text = _decision._candidate_row_text
_candidate_leaf_text = _decision._candidate_leaf_text
_candidate_context_text = _decision._candidate_context_text
_phrase_matches = _decision._phrase_matches
_row_phrase_matches_by_slot = _decision._row_phrase_matches_by_slot
search_expansion_adds_slot_coverage = _decision.search_expansion_adds_slot_coverage
_semantic_candidate_score = _decision._semantic_candidate_score
decision_from_semantic_plan = _decision.decision_from_semantic_plan


def _unit_kind(unit: str) -> str:
    return _ratio_options._unit_kind(unit)


_candidate_groups = _decision._candidate_groups
_same_unit_kind = _decision._same_unit_kind
_same_row_labels = _decision._same_row_labels
_clear_slot_gaps = _decision._clear_slot_gaps
_strong_total_series = _decision._strong_total_series
_strong_same_metric_series = _decision._strong_same_metric_series
deterministic_decision = _decision.deterministic_decision
_expected_candidate_count = _decision._expected_candidate_count
normalize_planner_decision = _decision.normalize_planner_decision
_normalized_from_unsupported = _decision._normalized_from_unsupported


_effective_target_unit = _validate._effective_target_unit
_validate_operation_unit_compatibility = _validate._validate_operation_unit_compatibility
_label_family = _validate._label_family
_is_total_candidate = _ratio_options._is_total_candidate
_candidate_family_label = _validate._candidate_family_label
_candidate_component_role = _ratio_options._candidate_component_role
_component_group_family = _validate._component_group_family
_component_role_family = _validate._component_role_family
_sum_values = _validate._sum_values
_effective_ratio_target_unit = _validate._effective_ratio_target_unit
validate_ratio_decision = _validate.validate_ratio_decision
ratio_decision_from_options = _validate.ratio_decision_from_options
validate_decision = _validate.validate_decision


def build_solution(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
    candidates: Sequence[RawCellCandidate],
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawCellCandidate]]:
    return _solution.build_solution(
        request,
        decision,
        candidates,
        frame_loader=load_frame,
        scale_expression_func=scale_expression,
        validate_decision_func=validate_decision,
    )


def build_ratio_solution(
    request: RawLinkRequest,
    decision: RawRatioDecision,
    candidates: Sequence[RawLinkedCandidate],
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawLinkedCandidate]]:
    return _solution.build_ratio_solution(
        request,
        decision,
        candidates,
        frame_loader=load_frame,
        validate_ratio_decision_func=validate_ratio_decision,
        candidate_table_ids_func=_candidate_table_ids,
        candidate_query_func=_candidate_query,
        candidate_first_cell_func=_candidate_first_cell,
    )


async def aprepare_raw_table_linker(
    state: Mapping[str, Any],
    *,
    use_planner: bool = False,
    planner_thinking: bool = False,
    use_ratio_groups: bool = False,
) -> dict[str, Any]:
    """Prepare a validated raw-table plan for graph execution."""
    return await _prepare.aprepare_raw_table_linker(
        state,
        use_planner=use_planner,
        planner_thinking=planner_thinking,
        use_ratio_groups=use_ratio_groups,
    )


__all__ = [
    "RAW_LINKER_SYSTEM",
    "RawCellCandidate",
    "RawGroupCandidate",
    "RawLinkRequest",
    "RawLinkerDecision",
    "RawOperation",
    "RawRatioDecision",
    "RawRatioSlotDecision",
    "RawSearchPlan",
    "RawSemanticPlan",
    "RawSlotSemanticConstraint",
    "RawScopeSlot",
    "RawTableLinkError",
    "aplan_raw_table_linker",
    "aplan_raw_ratio_linker",
    "aplan_raw_search",
    "aplan_raw_semantics",
    "aprepare_raw_table_linker",
    "build_candidates",
    "build_ratio_candidates",
    "build_ratio_solution",
    "build_request",
    "build_solution",
    "deterministic_decision",
    "decision_from_semantic_plan",
    "normalize_planner_decision",
    "render_candidates",
    "render_table_contexts",
    "request_with_search_plan",
    "semantic_plan_from_search_plan",
    "search_expansion_adds_slot_coverage",
    "should_attempt_raw_table_linker",
    "validate_decision",
    "validate_ratio_decision",
]
