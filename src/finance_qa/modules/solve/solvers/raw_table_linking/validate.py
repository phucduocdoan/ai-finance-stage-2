"""Validation helpers for raw-table linker decisions."""
from __future__ import annotations

import re
from typing import Sequence

from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.units import MONEY_SCALE
from finance_qa.modules.solve.solvers.raw_table_linking import decision as _decision
from finance_qa.modules.solve.solvers.raw_table_linking import ratio_options as _ratio_options
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawLinkerDecision,
    RawRatioDecision,
    RawRatioOption,
    RawRatioOptionDecision,
    RawRatioSlotDecision,
    RawTableLinkError,
)
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawCellCandidate,
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)


def _effective_target_unit(request: RawLinkRequest, decision: RawLinkerDecision) -> str:
    return decision.target_unit if decision.target_unit != "unknown" else request.target_unit


def _validate_operation_unit_compatibility(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
    chosen: Sequence[RawCellCandidate],
) -> None:
    target = _effective_target_unit(request, decision)
    kinds = {_ratio_options._unit_kind(candidate.source_unit) for candidate in chosen}
    if len(kinds) > 1:
        raise RawTableLinkError(f"mixed unit kinds: {sorted(kinds)}")
    if not kinds:
        return
    source_kind = next(iter(kinds))
    if target in {"ratio", "percent"} and source_kind == "money" and request.operation != "ratio":
        raise RawTableLinkError("ratio/percent target cannot be answered by money-cell arithmetic")
    if target in MONEY_SCALE and source_kind in {"ratio", "percent"}:
        raise RawTableLinkError("money target cannot be answered by ratio/percent cells")


def _label_family(label: str) -> str:
    without_parenthetical = re.sub(r"\([^)]*\)", " ", label)
    norm = _norm(without_parenthetical)
    norm = re.sub(r"^(?:\d+|[ivxlcdm]+)\s+", "", norm).strip()
    return norm


def _candidate_family_label(candidate: RawLinkedCandidate) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.label.split("::", 1)[0]
    return candidate.row_path_text


def _component_group_family(candidates: Sequence[RawLinkedCandidate]) -> str:
    if candidates and all(_ratio_options._is_total_candidate(candidate) for candidate in candidates):
        return "total"
    families = sorted({
        family
        for candidate in candidates
        if (family := _label_family(_candidate_family_label(candidate)))
    })
    return " + ".join(families)


def _component_role_family(candidates: Sequence[RawLinkedCandidate]) -> str:
    roles = sorted({
        role
        for candidate in candidates
        if (role := _ratio_options._candidate_component_role(candidate))
    })
    return " + ".join(roles)


def _sum_values(candidates: Sequence[RawLinkedCandidate]) -> float:
    return sum(candidate.value for candidate in candidates)


def _effective_ratio_target_unit(request: RawLinkRequest, decision: RawRatioDecision) -> str:
    return decision.target_unit if decision.target_unit != "unknown" else request.target_unit


def validate_ratio_decision(
    request: RawLinkRequest,
    decision: RawRatioDecision,
    candidates: Sequence[RawLinkedCandidate],
    *,
    min_candidate_score: float = 0.18,
    max_side_terms: int = 6,
) -> list[tuple[str, list[RawLinkedCandidate], list[RawLinkedCandidate]]]:
    if not decision.supported:
        raise RawTableLinkError(decision.reason or "ratio planner marked unsupported")
    if request.operation != "ratio" or decision.operation != "ratio":
        raise RawTableLinkError(f"ratio operation mismatch: {decision.operation} != {request.operation}")

    expected_slots = [slot.key for slot in request.slots]
    decision_slots = [slot.slot_key for slot in decision.slots]
    if decision_slots != expected_slots:
        raise RawTableLinkError(f"ratio slot mismatch: {decision_slots} != {expected_slots}")

    by_id = {candidate.id: candidate for candidate in candidates}
    selections: list[tuple[str, list[RawLinkedCandidate], list[RawLinkedCandidate]]] = []
    for slot_decision in decision.slots:
        if not slot_decision.numerator_candidate_ids or not slot_decision.denominator_candidate_ids:
            raise RawTableLinkError(f"ratio slot {slot_decision.slot_key} needs numerator and denominator")
        if (
            len(slot_decision.numerator_candidate_ids) > max_side_terms
            or len(slot_decision.denominator_candidate_ids) > max_side_terms
        ):
            raise RawTableLinkError(f"ratio slot {slot_decision.slot_key} has too many component ids")
        all_ids = [*slot_decision.numerator_candidate_ids, *slot_decision.denominator_candidate_ids]
        if len(all_ids) != len(set(all_ids)):
            raise RawTableLinkError(f"ratio slot {slot_decision.slot_key} repeats a candidate id")

        numerator: list[RawLinkedCandidate] = []
        denominator: list[RawLinkedCandidate] = []
        for ids, target in (
            (slot_decision.numerator_candidate_ids, numerator),
            (slot_decision.denominator_candidate_ids, denominator),
        ):
            for cid in ids:
                candidate = by_id.get(cid)
                if candidate is None:
                    raise RawTableLinkError(f"unknown ratio candidate id {cid}")
                if candidate.slot_key != slot_decision.slot_key:
                    raise RawTableLinkError(
                        f"ratio candidate {cid} belongs to {candidate.slot_key}, not {slot_decision.slot_key}"
                    )
                if candidate.score < min_candidate_score:
                    raise RawTableLinkError("selected ratio candidate score below threshold")
                target.append(candidate)

        kinds = {_ratio_options._unit_kind(candidate.source_unit) for candidate in [*numerator, *denominator]}
        if len(kinds) > 1:
            raise RawTableLinkError(f"ratio candidates have mixed unit kinds: {sorted(kinds)}")
        if len(numerator) > 1 and any(_ratio_options._is_total_candidate(candidate) for candidate in numerator):
            raise RawTableLinkError(f"ratio numerator mixes a total row with components for {slot_decision.slot_key}")
        if len(denominator) > 1 and any(_ratio_options._is_total_candidate(candidate) for candidate in denominator):
            raise RawTableLinkError(f"ratio denominator mixes a total row with components for {slot_decision.slot_key}")
        if _sum_values(denominator) == 0.0:
            raise RawTableLinkError(f"ratio denominator is zero for {slot_decision.slot_key}")
        selections.append((slot_decision.slot_key, numerator, denominator))

    target_unit = _effective_ratio_target_unit(request, decision)
    if target_unit not in {"unknown", "ratio", "percent"}:
        raise RawTableLinkError(f"ratio target unit is not scale-free: {target_unit}")

    if len(selections) > 1:
        numerator_roles = {_component_role_family(numerator) for _, numerator, _ in selections}
        denominator_roles = {_component_role_family(denominator) for _, _, denominator in selections}
        numerator_families = {_component_group_family(numerator) for _, numerator, _ in selections}
        denominator_families = {_component_group_family(denominator) for _, _, denominator in selections}
        if "" not in numerator_roles and len(numerator_roles) == 1:
            numerator_families = set()
        if "" not in denominator_roles and len(denominator_roles) == 1:
            denominator_families = set()
        if len(numerator_families) > 1:
            raise RawTableLinkError(f"ratio numerator components differ across slots: {sorted(numerator_families)}")
        if len(denominator_families) > 1:
            raise RawTableLinkError(f"ratio denominator components differ across slots: {sorted(denominator_families)}")

    return selections


def ratio_decision_from_options(
    request: RawLinkRequest,
    decision: RawRatioOptionDecision,
    options: Sequence[RawRatioOption],
) -> RawRatioDecision:
    if not decision.supported:
        return RawRatioDecision(
            supported=False,
            operation="ratio",
            target_unit=decision.target_unit,
            confidence=decision.confidence,
            reason=decision.reason or "ratio option planner marked unsupported",
        )
    expected_slots = [slot.key for slot in request.slots]
    option_slots = [slot.slot_key for slot in decision.slots]
    if option_slots != expected_slots:
        return RawRatioDecision(
            supported=False,
            operation="ratio",
            target_unit=decision.target_unit,
            reason=f"ratio option slot mismatch: {option_slots} != {expected_slots}",
        )
    by_id = {option.id: option for option in options}
    slots: list[RawRatioSlotDecision] = []
    for slot_decision in decision.slots:
        numerator = by_id.get(slot_decision.numerator_option_id)
        denominator = by_id.get(slot_decision.denominator_option_id)
        if numerator is None:
            return RawRatioDecision(
                supported=False,
                operation="ratio",
                target_unit=decision.target_unit,
                reason=f"unknown numerator option id {slot_decision.numerator_option_id}",
            )
        if denominator is None:
            return RawRatioDecision(
                supported=False,
                operation="ratio",
                target_unit=decision.target_unit,
                reason=f"unknown denominator option id {slot_decision.denominator_option_id}",
            )
        if numerator.slot_key != slot_decision.slot_key or numerator.side != "numerator":
            return RawRatioDecision(
                supported=False,
                operation="ratio",
                target_unit=decision.target_unit,
                reason=f"invalid numerator option {numerator.id} for {slot_decision.slot_key}",
            )
        if denominator.slot_key != slot_decision.slot_key or denominator.side != "denominator":
            return RawRatioDecision(
                supported=False,
                operation="ratio",
                target_unit=decision.target_unit,
                reason=f"invalid denominator option {denominator.id} for {slot_decision.slot_key}",
            )
        slots.append(
            RawRatioSlotDecision(
                slot_key=slot_decision.slot_key,
                numerator_candidate_ids=numerator.candidate_ids,
                denominator_candidate_ids=denominator.candidate_ids,
                reason=slot_decision.reason,
            )
        )
    return RawRatioDecision(
        supported=True,
        operation="ratio",
        slots=slots,
        target_unit=decision.target_unit if decision.target_unit != "unknown" else request.target_unit,
        confidence=decision.confidence,
        reason=decision.reason or "ratio options selected",
    )


def validate_decision(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
    candidates: Sequence[RawCellCandidate],
    *,
    min_candidate_score: float = 0.24,
) -> list[RawCellCandidate]:
    if not decision.supported:
        raise RawTableLinkError(decision.reason or "planner marked unsupported")
    if decision.operation != request.operation:
        raise RawTableLinkError(f"operation mismatch: {decision.operation} != {request.operation}")
    if request.operation == "direct" and request.target_unit == "ratio":
        raise RawTableLinkError("single-cell direct request cannot answer a ratio")
    by_id = {candidate.id: candidate for candidate in candidates}
    chosen: list[RawCellCandidate] = []
    for cid in decision.candidate_ids:
        candidate = by_id.get(cid)
        if candidate is None:
            raise RawTableLinkError(f"unknown candidate id {cid}")
        chosen.append(candidate)
    if len(chosen) != len(set(c.id for c in chosen)):
        raise RawTableLinkError("duplicate candidate id")

    expected = _decision._expected_candidate_count(request)
    if len(chosen) != expected:
        raise RawTableLinkError(f"needs {expected} candidates, got {len(chosen)}")

    slot_order = [slot.key for slot in request.slots]
    chosen_slots = [candidate.slot_key for candidate in chosen]
    if request.operation in {"diff", "sum", "avg"} and chosen_slots != slot_order:
        raise RawTableLinkError(f"candidate order/scope mismatch: {chosen_slots} != {slot_order}")
    if any(candidate.score < min_candidate_score for candidate in chosen):
        raise RawTableLinkError("selected candidate score below threshold")
    if request.operation == "direct" and any(candidate.score < _decision._MIN_DIRECT_SCORE for candidate in chosen):
        raise RawTableLinkError("direct candidate evidence below threshold")
    if any(candidate.value == 0.0 for candidate in chosen):
        raise RawTableLinkError("selected candidate value is zero")
    if _decision._normalized_from_unsupported(decision) and request.operation in {"diff", "sum", "avg"}:
        coherent = _decision._same_row_labels(chosen) or (
            request.wants_total and all(candidate.is_total_row for candidate in chosen)
        )
        if not coherent:
            raise RawTableLinkError("unsupported planner ids need coherent row evidence")

    _validate_operation_unit_compatibility(request, decision, chosen)
    return chosen


__all__ = [
    "_candidate_family_label",
    "_component_group_family",
    "_component_role_family",
    "_effective_ratio_target_unit",
    "_effective_target_unit",
    "_label_family",
    "_sum_values",
    "_validate_operation_unit_compatibility",
    "ratio_decision_from_options",
    "validate_decision",
    "validate_ratio_decision",
]
