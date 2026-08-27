"""Ratio option construction and deterministic selection."""
from __future__ import annotations

import re
from typing import Any, Sequence

from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.common.units import MONEY_SCALE
from finance_qa.modules.solve.solvers.raw_table_linking import candidates as _candidates
from finance_qa.modules.solve.solvers.raw_table_linking import render as _render
from finance_qa.modules.solve.solvers.raw_table_linking import scoring as _scoring
from finance_qa.modules.solve.solvers.raw_table_linking.schema import (
    RawRatioOption,
    RawRatioOptionDecision,
    RawRatioOptionSlotDecision,
)
from finance_qa.modules.solve.solvers.table_linking.schema import (
    RawCellCandidate,
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
)


def _unit_kind(unit: str) -> str:
    if unit in MONEY_SCALE or unit == "unknown":
        return "money"
    return unit


def _is_total_candidate(candidate: RawLinkedCandidate) -> bool:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.semantic_role == "total"
    return candidate.is_total_row


def _candidate_component_role(candidate: RawLinkedCandidate) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.semantic_role
    return _scoring._component_role_from_text(
        _norm(f"{candidate.row_path_text} {candidate.column}"),
        is_total=candidate.is_total_row,
    )


def _ratio_side_for_candidate(request: RawLinkRequest, candidate: RawLinkedCandidate) -> set[str]:
    role = _candidate_component_role(candidate)
    out: set[str] = set()
    numerator_roles = _candidates._ratio_numerator_roles(request)
    if role in numerator_roles:
        out.add("numerator")
    if role == "total" or _is_total_candidate(candidate):
        out.add("denominator")
    if isinstance(candidate, RawCellCandidate):
        text = _norm(f"{candidate.row_path_text} {candidate.column}")
        if (
            "lt_1y" in numerator_roles
            and ("ngan han" in text or "duoi 1 nam" in text or "duoi mot nam" in text)
        ):
            out.add("numerator")
        if candidate.is_total_row or re.search(r"\b(?:tong\s+cong|cong)\b", text):
            out.add("denominator")
        if not out and role == "" and not candidate.is_total_row and candidate.score >= 0.5:
            out.add("numerator")
    return out


def _ratio_option_label(candidate: RawLinkedCandidate) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.label
    return f"{candidate.row_path_text} :: {candidate.column}"


def _candidate_context(candidate: RawLinkedCandidate) -> str:
    return candidate.table_context


def _ratio_option_period_rank(request: RawLinkRequest, candidate: RawLinkedCandidate) -> int:
    if not isinstance(candidate, RawCellCandidate):
        return 0
    text = _norm(candidate.column)
    if request.period in {"current", "annual", "unknown"}:
        if _scoring._CURRENT_COL.search(text):
            return 1
        if _scoring._PRIOR_COL.search(text):
            return -1
    if request.period == "prior":
        if _scoring._PRIOR_COL.search(text):
            return 1
        if _scoring._CURRENT_COL.search(text):
            return -1
    return 0


def _ratio_option_column_score(candidate: RawLinkedCandidate) -> float:
    if isinstance(candidate, RawCellCandidate):
        return candidate.column_score
    return 0.0


def _ratio_option_table_score(candidate: RawLinkedCandidate) -> float:
    if isinstance(candidate, RawCellCandidate):
        return candidate.table_score
    return 0.0


def _ratio_option_evidence_rank(
    request: RawLinkRequest,
    candidate: RawLinkedCandidate,
    side: str,
) -> int:
    if isinstance(candidate, RawCellCandidate):
        role = _candidate_component_role(candidate)
        if side == "numerator" and role in _candidates._ratio_numerator_roles(request):
            return 2
        if side == "denominator" and _is_total_candidate(candidate):
            return 2
    if isinstance(candidate, RawGroupCandidate):
        return 1
    return 0


def build_ratio_options(
    request: RawLinkRequest,
    candidates: Sequence[RawLinkedCandidate],
    *,
    max_options_per_side: int = 8,
) -> tuple[list[RawRatioOption], dict[str, Any]]:
    """Partition mixed candidates into complete numerator/denominator options."""
    options: list[RawRatioOption] = []
    counts: dict[str, dict[str, int]] = {
        slot.key: {"numerator": 0, "denominator": 0}
        for slot in request.slots
    }
    side_counts = {"numerator": 0, "denominator": 0}
    missing: list[str] = []
    for slot in request.slots:
        slot_candidates = [
            candidate for candidate in candidates
            if candidate.slot_key == slot.key and candidate.score >= 0.18
        ]
        per_side: dict[str, list[RawLinkedCandidate]] = {"numerator": [], "denominator": []}
        for candidate in slot_candidates:
            for side in _ratio_side_for_candidate(request, candidate):
                per_side[side].append(candidate)
        for side in ("numerator", "denominator"):
            per_side[side].sort(
                key=lambda candidate: (
                    -_ratio_option_evidence_rank(request, candidate, side),
                    -candidate.score,
                    -_ratio_option_period_rank(request, candidate),
                    -_ratio_option_table_score(candidate),
                    -_ratio_option_column_score(candidate),
                    _ratio_option_label(candidate),
                    ",".join(_render._candidate_table_ids(candidate)),
                )
            )
            kept = per_side[side][:max_options_per_side]
            counts[slot.key][side] = len(kept)
            if not kept:
                missing.append(f"{slot.key}:{side}")
            for candidate in kept:
                prefix = "n" if side == "numerator" else "d"
                side_counts[side] += 1
                options.append(
                    RawRatioOption(
                        id=f"{prefix}{side_counts[side]}",
                        slot_key=slot.key,
                        side=side,  # type: ignore[arg-type]
                        candidate_ids=[candidate.id],
                        source_kind="group" if isinstance(candidate, RawGroupCandidate) else "cell",
                        label=_ratio_option_label(candidate),
                        semantic_role=_candidate_component_role(candidate),
                        value=float(candidate.value),
                        unit=(candidate.source_unit or "unknown"),  # type: ignore[arg-type]
                        table_ids=_render._candidate_table_ids(candidate),
                        context=_scoring._short_context(_candidate_context(candidate), 220),
                        score=candidate.score,
                    )
                )
    return options, {
        "option_count": len(options),
        "per_slot_side": counts,
        "missing_options": missing,
    }


def deterministic_ratio_option_decision(
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
) -> RawRatioOptionDecision:
    if request.operation != "ratio":
        return RawRatioOptionDecision(
            supported=False,
            operation="ratio",
            reason=f"deterministic ratio options do not handle {request.operation}",
        )
    by_slot: dict[str, dict[str, list[RawRatioOption]]] = {
        slot.key: {"numerator": [], "denominator": []}
        for slot in request.slots
    }
    for option in options:
        if option.slot_key in by_slot:
            by_slot[option.slot_key][option.side].append(option)

    chosen_slots: list[RawRatioOptionSlotDecision] = []
    selected: list[RawRatioOption] = []
    for slot in request.slots:
        numerator = by_slot[slot.key]["numerator"]
        denominator = by_slot[slot.key]["denominator"]
        if not numerator or not denominator:
            return RawRatioOptionDecision(
                supported=False,
                operation="ratio",
                reason=f"missing deterministic options for {slot.key}",
            )
        top_num = numerator[0]
        top_den = denominator[0]
        numerator_roles = _candidates._ratio_numerator_roles(request)
        numerator_ok = (
            top_num.semantic_role in numerator_roles
            or (top_num.source_kind == "cell" and not top_num.semantic_role and top_num.score >= 0.55)
        )
        denominator_ok = top_den.semantic_role == "total"
        if not numerator_ok or not denominator_ok:
            return RawRatioOptionDecision(
                supported=False,
                operation="ratio",
                reason=f"top options are not semantically clear for {slot.key}",
            )
        chosen_slots.append(
            RawRatioOptionSlotDecision(
                slot_key=slot.key,
                numerator_option_id=top_num.id,
                denominator_option_id=top_den.id,
                reason="deterministic top option per ratio side",
            )
        )
        selected.extend([top_num, top_den])

    unit_kinds = {_unit_kind(option.unit) for option in selected}
    if len(unit_kinds) > 1:
        return RawRatioOptionDecision(
            supported=False,
            operation="ratio",
            reason=f"deterministic options have mixed unit kinds: {sorted(unit_kinds)}",
        )
    if len(chosen_slots) > 1:
        numerator_roles = {option.semantic_role for option in selected[::2] if option.semantic_role}
        denominator_roles = {option.semantic_role for option in selected[1::2] if option.semantic_role}
        if len(numerator_roles) != 1 or denominator_roles != {"total"}:
            return RawRatioOptionDecision(
                supported=False,
                operation="ratio",
                reason="deterministic options are not role-consistent across slots",
            )

    return RawRatioOptionDecision(
        supported=True,
        operation="ratio",
        slots=chosen_slots,
        target_unit=request.target_unit,
        confidence=0.0,
        reason="deterministic top option per ratio side",
    )


def _prefer_ratio_option_surface(request: RawLinkRequest) -> bool:
    """Use option selection for repeated maturity-ratio surfaces.

    Multi-component ratios such as debt-borrowings/total-assets still need the
    flat candidate planner because one numerator side can require several cells.
    """
    all_maturity_roles = {"lt_1y", "1_to_5y", "gt_5y"}
    return request.ratio_aggregate == "avg" and _candidates._ratio_numerator_roles(request) != all_maturity_roles


__all__ = [
    "_candidate_component_role",
    "_candidate_context",
    "_is_total_candidate",
    "_prefer_ratio_option_surface",
    "_ratio_option_column_score",
    "_ratio_option_evidence_rank",
    "_ratio_option_label",
    "_ratio_option_period_rank",
    "_ratio_option_table_score",
    "_ratio_side_for_candidate",
    "_unit_kind",
    "build_ratio_options",
    "deterministic_ratio_option_decision",
]
