"""Deterministic and semantic decisions for raw-table linking."""
from __future__ import annotations

from typing import Mapping, Sequence

from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.solvers.raw_table_linking import ratio_options as _ratio_options
from finance_qa.modules.solve.solvers.raw_table_linking.request import _tokens
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawSearchPlan,
    RawSemanticPlan,
    RawSlotSemanticConstraint,
)
from finance_qa.modules.solve.solvers.table_linking.schema import (
    RawCellCandidate,
    RawLinkRequest,
)


_MIN_DIRECT_SCORE = 0.84
_NORMALIZED_UNSUPPORTED_REASON = "complete candidate_ids supplied despite unsupported:"


def _candidate_semantic_text(candidate: RawCellCandidate) -> str:
    return _norm(f"{candidate.row_path_text} {candidate.column} {candidate.table_context}")


def _candidate_row_text(candidate: RawCellCandidate) -> str:
    return _norm(candidate.row_path_text)


def _candidate_leaf_text(candidate: RawCellCandidate) -> str:
    return _norm(candidate.row_label)


def _candidate_context_text(candidate: RawCellCandidate) -> str:
    return _norm(candidate.table_context)


def _phrase_matches(text_norm: str, phrase: str) -> bool:
    phrase_norm = _norm(phrase)
    if not phrase_norm:
        return False
    if phrase_norm in text_norm:
        return True
    phrase_tokens = _tokens(phrase_norm)
    if len(phrase_tokens) < 2:
        return False
    text_tokens = set(_tokens(text_norm))
    return all(token in text_tokens for token in phrase_tokens)


def _row_phrase_matches_by_slot(
    candidates: Sequence[RawCellCandidate],
    phrase: str,
) -> dict[str, list[RawCellCandidate]]:
    out: dict[str, list[RawCellCandidate]] = {}
    for candidate in candidates:
        if _phrase_matches(_candidate_row_text(candidate), phrase):
            out.setdefault(candidate.slot_key, []).append(candidate)
    return out


def search_expansion_adds_slot_coverage(
    request: RawLinkRequest,
    plan: RawSearchPlan | None,
    initial_candidates: Sequence[RawCellCandidate],
    expanded_candidates: Sequence[RawCellCandidate],
    *,
    max_matches_per_slot: int = 3,
) -> bool:
    """Use search expansion only when it adds real row evidence for every slot."""
    if plan is None or not plan.supported:
        return False
    slot_keys = {slot.key for slot in request.slots}
    if not slot_keys:
        return False
    for phrase in plan.row_phrases:
        initial = _row_phrase_matches_by_slot(initial_candidates, phrase)
        expanded = _row_phrase_matches_by_slot(expanded_candidates, phrase)
        if set(expanded) != slot_keys or set(initial) == slot_keys:
            continue
        if all(0 < len(expanded[slot_key]) <= max_matches_per_slot for slot_key in slot_keys):
            return True
    return False


def _semantic_candidate_score(
    candidate: RawCellCandidate,
    constraint: RawSlotSemanticConstraint,
) -> float | None:
    text_norm = _candidate_semantic_text(candidate)
    row_norm = _candidate_row_text(candidate)
    leaf_norm = _candidate_leaf_text(candidate)
    context_norm = _candidate_context_text(candidate)
    # A row whose own label names the metric is stronger evidence than one that
    # only borrows wording from an ancestor section header.
    leaf_hits = sum(
        1 for phrase in constraint.row_phrases
        if _phrase_matches(leaf_norm, phrase)
    )
    path_hits = sum(
        1 for phrase in constraint.row_phrases
        if _phrase_matches(row_norm, phrase)
    ) - leaf_hits
    row_hits = leaf_hits + path_hits
    if constraint.row_phrases and row_hits == 0:
        return None
    context_hits = sum(
        1 for phrase in constraint.context_phrases
        if _phrase_matches(context_norm, phrase)
    )
    if constraint.context_phrases and context_hits == 0:
        return None
    include_hits = sum(
        1 for phrase in constraint.include_phrases
        if _phrase_matches(text_norm, phrase)
    )
    if constraint.include_phrases and include_hits == 0:
        return None
    if any(
        _phrase_matches(_norm(f"{candidate.row_path_text} {candidate.column}"), phrase)
        for phrase in constraint.exclude_phrases
    ):
        return None
    if constraint.prefer_total_row and not candidate.is_total_row:
        return None
    total_bonus = 0.12 if constraint.prefer_total_row and candidate.is_total_row else 0.0
    return (
        candidate.score
        + leaf_hits * 0.24
        + path_hits * 0.10
        + context_hits * 0.12
        + include_hits * 0.16
        + total_bonus
    )


def decision_from_semantic_plan(
    request: RawLinkRequest,
    plan: RawSemanticPlan,
    candidates: Sequence[RawCellCandidate],
    *,
    min_candidate_score: float = 0.18,
) -> RawLinkerDecision:
    if not plan.supported:
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason=plan.reason or "semantic planner marked unsupported",
        )
    if plan.operation != request.operation:
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason=f"semantic operation mismatch: {plan.operation} != {request.operation}",
        )
    slot_order = [slot.key for slot in request.slots]
    constraints = {constraint.slot_key: constraint for constraint in plan.slots}
    if set(constraints) != set(slot_order):
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason=f"semantic slot mismatch: {sorted(constraints)} != {slot_order}",
        )

    chosen: list[RawCellCandidate] = []
    for slot_key in slot_order:
        constraint = constraints[slot_key]
        has_positive = (
            constraint.row_phrases
            or constraint.context_phrases
            or constraint.include_phrases
            or constraint.prefer_total_row
        )
        if not has_positive:
            return RawLinkerDecision(
                supported=False,
                operation=request.operation,
                reason=f"semantic constraint for {slot_key} has no positive evidence",
            )
        scored: list[tuple[float, RawCellCandidate]] = []
        for candidate in candidates:
            if candidate.slot_key != slot_key or candidate.score < min_candidate_score:
                continue
            semantic_score = _semantic_candidate_score(candidate, constraint)
            if semantic_score is None:
                continue
            scored.append((semantic_score, candidate))
        if not scored:
            return RawLinkerDecision(
                supported=False,
                operation=request.operation,
                reason=f"semantic constraints matched no candidate for {slot_key}",
            )
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1].score,
                -item[1].row_score,
                -item[1].table_score,
                -item[1].column_score,
                item[1].table_id,
                item[1].row_position,
            )
        )
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04:
            return RawLinkerDecision(
                supported=False,
                operation=request.operation,
                reason=f"semantic candidates are ambiguous for {slot_key}",
            )
        chosen.append(scored[0][1])

    if not _same_unit_kind(chosen):
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason="semantic candidates have mixed unit kinds",
        )
    confidence = min(candidate.score for candidate in chosen) + 0.16
    return RawLinkerDecision(
        supported=True,
        operation=request.operation,
        candidate_ids=[candidate.id for candidate in chosen],
        target_unit=plan.target_unit if plan.target_unit != "unknown" else request.target_unit,
        confidence=min(0.97, confidence),
        reason=plan.reason or "semantic constraints matched candidates",
    )


def _candidate_groups(
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
) -> tuple[list[RawCellCandidate], dict[str, list[RawCellCandidate]], str]:
    by_slot: dict[str, list[RawCellCandidate]] = {slot.key: [] for slot in request.slots}
    for candidate in candidates:
        if candidate.slot_key in by_slot:
            by_slot[candidate.slot_key].append(candidate)
    chosen: list[RawCellCandidate] = []
    for slot in request.slots:
        slot_candidates = sorted(
            by_slot[slot.key],
            key=lambda c: (
                -c.score,
                -c.row_score,
                -c.table_score,
                -c.column_score,
                c.table_id,
                c.row_position,
            ),
        )
        by_slot[slot.key] = slot_candidates
        if not slot_candidates:
            return [], by_slot, f"missing candidates for slot {slot.key}"
        chosen.append(slot_candidates[0])
    return chosen, by_slot, ""


def _same_unit_kind(candidates: Sequence[RawCellCandidate]) -> bool:
    return len({_ratio_options._unit_kind(candidate.source_unit) for candidate in candidates}) <= 1


def _same_row_labels(candidates: Sequence[RawCellCandidate]) -> bool:
    labels = {_norm(candidate.row_path_text) for candidate in candidates}
    return len(labels) == 1


def _clear_slot_gaps(
    chosen: Sequence[RawCellCandidate],
    by_slot: Mapping[str, Sequence[RawCellCandidate]],
    *,
    min_gap: float = 0.06,
) -> bool:
    for candidate in chosen:
        slot_candidates = by_slot.get(candidate.slot_key) or []
        if len(slot_candidates) > 1 and candidate.score - slot_candidates[1].score < min_gap:
            return False
    return True


def _strong_total_series(candidates: Sequence[RawCellCandidate]) -> bool:
    return all(
        candidate.is_total_row
        and candidate.score >= 0.86
        and candidate.column_score >= 0.3
        and (candidate.row_score >= 0.7 or candidate.table_score >= 0.7)
        for candidate in candidates
    )


def _strong_same_metric_series(candidates: Sequence[RawCellCandidate]) -> bool:
    if not _same_row_labels(candidates):
        return False
    if len(_tokens(candidates[0].row_path_text)) < 4:
        return False
    return all(candidate.score >= 0.7 and candidate.column_score >= 0.3 for candidate in candidates)


def deterministic_decision(
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
) -> RawLinkerDecision:
    """Choose top-ranked cells when the score pattern is strong enough."""
    chosen, by_slot, reason = _candidate_groups(request, candidates)
    if reason:
        return RawLinkerDecision(supported=False, operation=request.operation, reason=reason)
    if request.operation == "direct":
        top = chosen[0]
        second = by_slot[top.slot_key][1] if len(by_slot[top.slot_key]) > 1 else None
        clear_gap = second is None or top.score - second.score >= 0.08
        if top.score >= _MIN_DIRECT_SCORE and (clear_gap or top.row_score >= 0.84 or top.score >= 0.9):
            return RawLinkerDecision(
                supported=True,
                operation=request.operation,
                candidate_ids=[top.id],
                target_unit=request.target_unit,
                confidence=min(0.97, max(0.7, top.score)),
                reason="deterministic top candidate",
            )
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason="top direct candidate is not clear enough",
        )

    if request.operation in {"diff", "sum", "avg"}:
        if not _same_unit_kind(chosen):
            return RawLinkerDecision(
                supported=False,
                operation=request.operation,
                reason="top candidates have mixed unit kinds",
            )
        strong = False
        if request.wants_total and request.operation in {"sum", "avg"}:
            strong = _strong_total_series(chosen)
        elif request.operation == "diff":
            strong = _strong_same_metric_series(chosen) and _clear_slot_gaps(chosen, by_slot)
        else:
            strong = _strong_same_metric_series(chosen) and _clear_slot_gaps(chosen, by_slot)
        if strong:
            confidence = min(candidate.score for candidate in chosen)
            return RawLinkerDecision(
                supported=True,
                operation=request.operation,
                candidate_ids=[candidate.id for candidate in chosen],
                target_unit=request.target_unit,
                confidence=min(0.97, max(0.72, confidence)),
                reason="deterministic slot-wise top candidates",
            )
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason="slot-wise top candidates are not strong enough",
        )

    return RawLinkerDecision(
        supported=False,
        operation=request.operation,
        reason=f"deterministic planner does not handle {request.operation}",
    )


def _expected_candidate_count(request: RawLinkRequest) -> int:
    if request.operation == "direct":
        return 1
    if request.operation == "ratio":
        return 2
    return len(request.slots)


def normalize_planner_decision(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
) -> RawLinkerDecision:
    """Resolve contradictory LLM output by treating complete ids as the decision."""
    if decision.supported:
        return decision
    if len(decision.candidate_ids) != _expected_candidate_count(request):
        return decision
    return decision.model_copy(update={
        "supported": True,
        "reason": f"{_NORMALIZED_UNSUPPORTED_REASON} {decision.reason}",
    })


def _normalized_from_unsupported(decision: RawLinkerDecision) -> bool:
    return decision.reason.startswith(_NORMALIZED_UNSUPPORTED_REASON)


__all__ = [
    "_NORMALIZED_UNSUPPORTED_REASON",
    "_candidate_context_text",
    "_candidate_groups",
    "_candidate_leaf_text",
    "_candidate_row_text",
    "_candidate_semantic_text",
    "_clear_slot_gaps",
    "_expected_candidate_count",
    "_normalized_from_unsupported",
    "_phrase_matches",
    "_row_phrase_matches_by_slot",
    "_same_row_labels",
    "_same_unit_kind",
    "_semantic_candidate_score",
    "_strong_same_metric_series",
    "_strong_total_series",
    "decision_from_semantic_plan",
    "deterministic_decision",
    "normalize_planner_decision",
    "search_expansion_adds_slot_coverage",
]
