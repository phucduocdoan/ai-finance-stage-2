"""Deterministic selection solver over the structured fact catalog.

This is a smaller and safer sibling of ``structured_facts``. It only builds a
plan when the question has one clear selection axis and the selector/answer
metrics are explicitly linked to the catalog text. There is no LLM planner here:
unsupported shapes fail closed to raw-table codegen.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from finance_qa.modules.solve.intent import (
    MAX_MARKER as _MAX_MARKER,
    MIN_MARKER as _MIN_MARKER,
)
from finance_qa.modules.solve.structured_facts import (
    DERIVED_ALIASES,
    MetricFilter,
    PRIMITIVES,
    StructuredFactError,
    StructuredPlan,
    execute_plan,
    metric_source_unit,
    supported_v1_plan,
)
from finance_qa.modules.solve.units import unit_from_hint


_NON_WORD = re.compile(r"[^a-z0-9%]+")
_FILTER_RE = re.compile(
    r"(?:lon\s+hon|tren|cao\s+hon|vuot)\s+(-?\d+(?:[,.]\d+)?)\s*(%)?|"
    r"(?:thap\s+hon|nho\s+hon|duoi)\s+(-?\d+(?:[,.]\d+)?)\s*(%)?"
)
_ANSWER_FIRST_CLAUSE = re.compile(
    r"\b(?:trong|tai|vao)\s+nam\s+co\b|\bnam\s+co\b|"
    r"\b(?:cong\s+ty|doanh\s+nghiep)\s+co\b"
)


def _norm(text: object) -> str:
    # Not `intent.norm`: `_FILTER_RE` above captures a trailing `%`, so this
    # normalisation keeps `%` instead of stripping it like the other solver
    # modules do.
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def _find_all(text: str, needle: str) -> list[int]:
    if not needle:
        return []
    out: list[int] = []
    start = 0
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            return out
        out.append(pos)
        start = pos + max(len(needle), 1)


@dataclass(frozen=True)
class MetricOccurrence:
    metric: str
    pos: int
    alias: str


class SelectionFactError(StructuredFactError):
    """Question is outside the deterministic selection fact slice."""


def _metric_aliases() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {}
    for key, metric in PRIMITIVES.items():
        aliases[key] = (key.replace("_", " "), *metric.aliases)
    for key, values in DERIVED_ALIASES.items():
        aliases[key] = (key.replace("_", " "), *values)
    return aliases


def _metric_occurrences(question: str) -> list[MetricOccurrence]:
    norm_question = _norm(question)
    hits: list[MetricOccurrence] = []
    seen: set[tuple[str, int]] = set()
    for metric, aliases in _metric_aliases().items():
        for alias in aliases:
            norm_alias = _norm(alias)
            if not norm_alias:
                continue
            for pos in _find_all(norm_question, norm_alias):
                key = (metric, pos)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(MetricOccurrence(metric=metric, pos=pos, alias=alias))
    return sorted(hits, key=lambda hit: (hit.pos, -len(_norm(hit.alias))))


def _hit_end(hit: MetricOccurrence) -> int:
    return hit.pos + len(_norm(hit.alias))


def _selection_axis(tickers: list[str], years: list[int]) -> tuple[str, str]:
    if len(tickers) == 1 and len(years) >= 2:
        return "year", ""
    if len(tickers) >= 2 and len(years) == 1:
        return "ticker", ""
    if len(tickers) >= 2 and len(years) >= 2:
        return "", "multi-axis selection outside deterministic selection_facts"
    return "", "selection needs one varying axis"


def _selection_order(norm_question: str) -> tuple[str, int, str]:
    max_match = _MAX_MARKER.search(norm_question)
    min_match = _MIN_MARKER.search(norm_question)
    if not max_match and not min_match:
        return "", -1, "no max/min selection marker"
    if max_match and (not min_match or max_match.start() <= min_match.start()):
        return "max", max_match.start(), ""
    return "min", min_match.start(), ""


def _target_unit(state: Mapping[str, Any], question: str) -> str:
    return (
        unit_from_hint(str(state.get("unit_hint") or ""))
        or unit_from_hint(question)
        or ""
    )


def _unit_compatible(metric: str, target_unit: str) -> bool:
    if not target_unit or target_unit == "unknown":
        return True
    source = metric_source_unit(metric)
    if source == "ratio":
        return target_unit in {"ratio", "percent"}
    if source == "year":
        return target_unit == "year"
    if source in {
        "vnd", "thousand_vnd", "million_vnd", "billion_vnd",
        "hundred_billion_vnd", "trillion_vnd",
    }:
        return target_unit in {
            "vnd", "thousand_vnd", "million_vnd", "billion_vnd",
            "hundred_billion_vnd", "trillion_vnd",
        }
    return True


def _closest_metric(
    occurrences: list[MetricOccurrence],
    marker_pos: int,
    *,
    exclude: set[str] | None = None,
    target_unit: str = "",
) -> str:
    exclude = exclude or set()
    candidates = [
        hit for hit in occurrences
        if hit.metric not in exclude and _unit_compatible(hit.metric, target_unit)
    ]
    if not candidates:
        return ""
    return min(candidates, key=lambda hit: (abs(hit.pos - marker_pos), hit.pos)).metric


def _selector_metric(
    occurrences: list[MetricOccurrence],
    marker_pos: int,
    *,
    exclude: set[str] | None = None,
) -> str:
    exclude = exclude or set()
    before = [hit for hit in occurrences if hit.pos < marker_pos and hit.metric not in exclude]
    candidates = before or [hit for hit in occurrences if hit.metric not in exclude]
    if not candidates:
        return ""
    return min(
        candidates,
        key=lambda hit: (
            abs(_hit_end(hit) - marker_pos),
            -len(_norm(hit.alias)),
            hit.pos,
        ),
    ).metric


def _answer_metric(
    occurrences: list[MetricOccurrence],
    norm_question: str,
    marker_pos: int,
    selector: str,
    filter_metric: str,
    target_unit: str,
) -> str:
    after = [
        hit for hit in occurrences
        if hit.pos > marker_pos
        and hit.metric not in {selector, filter_metric}
        and _unit_compatible(hit.metric, target_unit)
    ]
    if after:
        return after[0].metric
    clause_matches = [
        match for match in _ANSWER_FIRST_CLAUSE.finditer(norm_question)
        if match.start() < marker_pos
    ]
    if clause_matches:
        cut = clause_matches[-1].start()
        before_clause = [
            hit for hit in occurrences
            if hit.pos < cut
            and hit.metric not in {selector, filter_metric}
            and _unit_compatible(hit.metric, target_unit)
        ]
        if before_clause:
            return min(before_clause, key=lambda hit: (hit.pos, -len(_norm(hit.alias)))).metric
    if _unit_compatible(selector, target_unit):
        return selector
    return ""


def _filter(
    occurrences: list[MetricOccurrence],
    norm_question: str,
    marker_pos: int,
) -> tuple[str, str, float | None]:
    matches = [match for match in _FILTER_RE.finditer(norm_question) if match.start() < marker_pos]
    if not matches:
        return "", "", None
    match = matches[-1]
    if match.group(1) is not None:
        relation = "gt"
        raw_value = match.group(1)
        percent = bool(match.group(2))
    else:
        relation = "lt"
        raw_value = match.group(3)
        percent = bool(match.group(4))
    try:
        value = float(str(raw_value).replace(",", "."))
    except ValueError:
        return "", "", None
    before = [hit for hit in occurrences if hit.pos < match.start()]
    if not before:
        return "", "", None
    metric = min(
        before,
        key=lambda hit: (
            abs(_hit_end(hit) - match.start()),
            -len(_norm(hit.alias)),
            -hit.pos,
        ),
    ).metric
    if percent and metric_source_unit(metric) == "ratio":
        value /= 100.0
    return metric, relation, value


def deterministic_selection_plan(state: Mapping[str, Any]) -> StructuredPlan:
    """Build a catalog-backed selection plan, or an unsupported plan."""
    question = str(state.get("question") or "")
    norm_question = _norm(question)
    order, marker_pos, reason = _selection_order(norm_question)
    if not order:
        return StructuredPlan(supported=False, operation="unsupported", reason=reason)

    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    years = sorted({int(y) for y in (state.get("years") or []) if y})
    axis, reason = _selection_axis(tickers, years)
    if not axis:
        return StructuredPlan(supported=False, operation="unsupported", reason=reason)

    occurrences = _metric_occurrences(question)
    if not occurrences:
        return StructuredPlan(
            supported=False,
            operation="unsupported",
            reason="no catalog metric anchored in question",
        )

    target = _target_unit(state, question)
    filter_metric, filter_relation, filter_value = _filter(
        occurrences, norm_question, marker_pos,
    )
    selector = _selector_metric(
        occurrences,
        marker_pos,
        exclude={filter_metric} if filter_metric else set(),
    )
    answer = _answer_metric(
        occurrences,
        norm_question,
        marker_pos,
        selector,
        filter_metric,
        target,
    )
    if not selector or not answer:
        return StructuredPlan(
            supported=False,
            operation="unsupported",
            reason="could not link selector and answer metrics",
        )

    plan = StructuredPlan(
        supported=True,
        operation="argmax" if order == "max" else "argmin",
        axis=axis,
        tickers=tickers,
        years=years,
        doc_type=str(state.get("doc_type") or "unknown"),
        selector_metric=selector,
        selector_order=order,
        answer_metric=answer,
        filters=[],
        target_unit=target,
    )
    if filter_metric and filter_relation and filter_value is not None:
        plan.filters = [
            MetricFilter(
                metric=filter_metric,
                relation=filter_relation,
                value=filter_value,
                value_source="literal",
            )
        ]
    return plan


def should_attempt_selection_facts(state: Mapping[str, Any]) -> tuple[bool, str]:
    plan = deterministic_selection_plan(state)
    if not plan.supported:
        return False, plan.reason or "unsupported selection_facts plan"
    ok, reason = supported_v1_plan(
        plan,
        str(state.get("question") or ""),
        str(state.get("unit_hint") or ""),
    )
    return ok, reason


async def asolve_selection_facts(state: Mapping[str, Any]) -> dict[str, Any]:
    plan = deterministic_selection_plan(state)
    if not plan.supported:
        raise SelectionFactError(plan.reason or "unsupported selection_facts plan")
    ok, reason = supported_v1_plan(
        plan,
        str(state.get("question") or ""),
        str(state.get("unit_hint") or ""),
    )
    if not ok:
        raise SelectionFactError(reason)
    return execute_plan(
        plan,
        question=str(state.get("question") or ""),
        unit_hint=str(state.get("unit_hint") or ""),
    )


__all__ = [
    "SelectionFactError",
    "asolve_selection_facts",
    "deterministic_selection_plan",
    "should_attempt_selection_facts",
]
