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

from finance_qa.modules.solve.common.intent import (
    ARITHMETIC_CONNECTOR as _ARITHMETIC_CONNECTOR,
    AVG_CUE as _AVG_CUE,
    CONDITIONED_TOTAL_CUE as _CONDITIONED_TOTAL_CUE,
    GROUP_COUNT_CUE as _COUNT_CUE,
    GROUP_SHARE_CUE as _SHARE_CUE,
    MAX_MARKER as _MAX_MARKER,
    MEDIAN_CUE as _MEDIAN_CUE,
    MEDIAN_FILTER_CUE as _MEDIAN_FILTER_CUE,
    MIN_MARKER as _MIN_MARKER,
    SCENARIO_CUE as _SCENARIO_CUE,
    SIGN_FILTER_CUE as _SIGN_FILTER_CUE,
    SUBGROUP_DIFF_CUE as _SUBGROUP_DIFF_CUE,
    SUM_CUE as _SUM_CUE,
    UNCONSUMED_COMPARATOR_CUE as _COMPARATOR_CUE,
)
from finance_qa.modules.solve.common.units import unit_from_hint
from finance_qa.modules.solve.facts.structured_facts import (
    DERIVED_ALIASES,
    MetricFilter,
    PRIMITIVES,
    StructuredFactError,
    StructuredPlan,
    execute_plan,
    metric_source_unit,
    supported_v1_plan,
)


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


def _metric_before(
    occurrences: list[MetricOccurrence],
    pos: int,
    *,
    max_gap: int | None = None,
) -> str:
    """The catalog metric the predicate at `pos` is talking about."""
    before = [hit for hit in occurrences if hit.pos < pos]
    if max_gap is not None:
        before = [hit for hit in before if pos - _hit_end(hit) <= max_gap]
    if not before:
        return ""
    return min(
        before,
        key=lambda hit: (
            abs(_hit_end(hit) - pos),
            -len(_norm(hit.alias)),
            -hit.pos,
        ),
    ).metric


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
    metric = _metric_before(occurrences, match.start())
    if not metric:
        return "", "", None
    if percent and metric_source_unit(metric) == "ratio":
        value /= 100.0
    return metric, relation, value


_NO_GROUP_FILTER = "no group filter to aggregate over"
_GT_COMPARATORS = ("lon hon", "cao hon", "tren", "vuot")
# A metric named more than this far before "duong"/"am" is not what the sign is
# predicating. The bound is what keeps company names out: "CTCP Duong Quang
# Ngai" and "Tap doan Dai Duong" contain the token but no nearby catalog metric.
_SIGN_MAX_GAP = 40


def _median_filters(
    occurrences: list[MetricOccurrence],
    norm_question: str,
    limit_pos: int,
) -> tuple[list[MetricFilter], list[tuple[int, int]]]:
    """Filters comparing a metric against the candidate set's own median.

    Returns the filters plus the spans they consumed, so the caller can tell a
    median *filter* from the median as the answer. A cue whose metric could not
    be linked consumes nothing on purpose: leaving its comparator unclaimed is
    what makes `_unexpressible` decline instead of dropping the condition.
    """
    filters: list[MetricFilter] = []
    spans: list[tuple[int, int]] = []
    for match in _MEDIAN_FILTER_CUE.finditer(norm_question):
        if match.start() >= limit_pos:
            continue
        metric = _metric_before(occurrences, match.start())
        if not metric:
            continue
        spans.append((match.start(), match.end()))
        relation = "gt" if match.group("cmp") in _GT_COMPARATORS else "lt"
        filters.append(
            MetricFilter(metric=metric, relation=relation, value=None, value_source="median")
        )
    return filters, spans


def _sign_filters(
    occurrences: list[MetricOccurrence],
    norm_question: str,
    limit_pos: int,
) -> list[MetricFilter]:
    """Filters on the sign of a metric ("CFO duong", "loi nhuan sau thue am")."""
    filters: list[MetricFilter] = []
    for match in _SIGN_FILTER_CUE.finditer(norm_question):
        if match.start() >= limit_pos:
            continue
        metric = _metric_before(occurrences, match.start(), max_gap=_SIGN_MAX_GAP)
        if not metric:
            continue
        relation = "lt" if match.group("sign") == "am" else "gt"
        filters.append(
            MetricFilter(metric=metric, relation=relation, value=0.0, value_source="literal")
        )
    return filters


def _all_filters(
    occurrences: list[MetricOccurrence],
    norm_question: str,
    limit_pos: int,
) -> tuple[list[MetricFilter], list[tuple[int, int]]]:
    """Every candidate filter stated before `limit_pos`, de-duplicated by metric.

    The numeric-threshold form keeps its existing "last match wins" behaviour
    rather than becoming a list: that arm is already in production and measured,
    and this change is only meant to add the two forms the emitter could not
    express at all.
    """
    filters, median_spans = _median_filters(occurrences, norm_question, limit_pos)
    filters += _sign_filters(occurrences, norm_question, limit_pos)
    metric, relation, value = _filter(occurrences, norm_question, limit_pos)
    if metric and relation and value is not None:
        filters.append(
            MetricFilter(metric=metric, relation=relation, value=value, value_source="literal")
        )
    deduped: list[MetricFilter] = []
    seen: set[tuple[str, str, float | None, str]] = set()
    for flt in filters:
        key = (flt.metric, flt.relation, flt.value, flt.value_source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(flt)
    return deduped, median_spans


def _aggregation(
    norm_question: str, median_spans: list[tuple[int, int]],
) -> tuple[str, int]:
    """Which aggregation the question applies to the surviving group.

    Ordered by specificity, not by position: a cardinality and a group share
    name what is being asked for outright, so they win over the cues that only
    say how the values combine. Count outranks share because "co bao nhieu cong
    ty" is unambiguous while share wording can co-occur with it. A `trung vi`
    already consumed by a median *filter* is not a median aggregation.
    """
    match = _COUNT_CUE.search(norm_question)
    if match:
        return "count", match.start()
    match = _SHARE_CUE.search(norm_question)
    if match:
        return "share", match.start()
    match = _AVG_CUE.search(norm_question)
    if match:
        return "mean", match.start()
    for match in _MEDIAN_CUE.finditer(norm_question):
        if not any(start <= match.start() < end for start, end in median_spans):
            return "median", match.start()
    match = _SUM_CUE.search(norm_question)
    if match:
        return "sum", match.start()
    return "", -1


_QUESTION_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_QUESTION_SYMBOL = re.compile(r"\b[A-Z]{3,4}\b")


def _scenario_adjustment(norm_question: str) -> str:
    # No `scenario_factor` and no stress expression is emitted here, so
    # answering would report the *unadjusted* figure.
    if _SCENARIO_CUE.search(norm_question):
        return "scenario adjustment not expressible as a filter_aggregate"
    return ""


def _subgroup_diff(norm_question: str) -> str:
    # "chenh lech ... giua phan nhom X va phan nhom con lai" needs two
    # groups; "trung binh chenh lech giua A va B" needs an expression.
    if _SUBGROUP_DIFF_CUE.search(norm_question):
        return "difference between metrics or subgroups is not a single aggregate"
    return ""


def _unconsumed_comparator(norm_question: str, median_spans: list[tuple[int, int]]) -> str:
    # A comparator no filter form consumed is an unmodelled condition.
    consumed = list(median_spans) + [m.span() for m in _FILTER_RE.finditer(norm_question)]
    for match in _COMPARATOR_CUE.finditer(norm_question):
        if not any(start <= match.start() < end for start, end in consumed):
            return f"unconsumed comparator {norm_question[match.start():match.end()]!r}"
    return ""


def _unnamed_sign_condition(norm_question: str, occurrences: list[MetricOccurrence]) -> str:
    """A sign condition on something the catalog cannot name.

    ("gia tri tai san rong chiu ap luc thanh ly am") emits no filter, so the
    group would be aggregated unfiltered. Rejecting here costs the false
    positives where the token is part of a company name ("CTCP Duong Quang
    Ngai"), which only ever means declining a question this branch might have
    answered.
    """
    for match in _SIGN_FILTER_CUE.finditer(norm_question):
        if not _metric_before(occurrences, match.start(), max_gap=_SIGN_MAX_GAP):
            return f"sign condition {match.group('sign')!r} names no catalog metric"
    return ""


def _composite_metric(norm_question: str, occurrences: list[MetricOccurrence]) -> str:
    # Two catalog metrics joined by arithmetic with no alias spanning the pair:
    # the question names a composite metric the catalog cannot express.
    ordered = sorted(occurrences, key=lambda hit: (hit.pos, _hit_end(hit)))
    for left, right in zip(ordered, ordered[1:]):
        gap = norm_question[_hit_end(left):right.pos]
        if not _ARITHMETIC_CONNECTOR.match(gap):
            continue
        if any(hit.pos <= left.pos and _hit_end(hit) >= _hit_end(right) for hit in occurrences):
            continue
        return f"composite metric {norm_question[left.pos:_hit_end(right)]!r} not in catalog"
    return ""


def _multi_year_scope(norm_question: str, years: list[int]) -> str:
    # `years` is one year by construction here, so a second year in the text is
    # a filter or answer scope this shape cannot carry ("duong trong ca ba nam
    # 2020-2022").
    mentioned = {int(y) for y in _QUESTION_YEAR.findall(norm_question)}
    if len(mentioned) > len(years):
        return f"question spans years {sorted(mentioned)} but the plan covers {years}"
    return ""


def _unmentioned_group_members(question: str, tickers: list[str]) -> str:
    """`tickers` comes from the retrieved documents, not from the question.

    For an argmax that only widens the field of candidates, but here the
    candidate set *is* the domain the answer is computed over -- one
    over-retrieved peer inflates a `count` outright and moves every other
    aggregation. So require the group to be enumerated by symbol in the
    question itself.

    This closes over-retrieval only: a question that lists five symbols while
    retrieval returned four still passes, and would silently aggregate four.
    Closing that direction needs a ticker universe to tell a real symbol from
    an acronym like "CTCP" or "CFO", which the fact store does not expose.
    """
    unmentioned = sorted(set(tickers) - set(_QUESTION_SYMBOL.findall(question)))
    if unmentioned:
        return f"candidate group members {unmentioned} are not named in the question"
    return ""


def _conditioned_share_denominator(norm_question: str, aggregation: str, agg_pos: int) -> str:
    # `share` divides by the whole candidate set; a restricted total would be
    # divided by the wrong denominator.
    if aggregation == "share" and _CONDITIONED_TOTAL_CUE.search(norm_question[agg_pos:]):
        return "group share denominator is itself conditioned"
    return ""


def _unexpressible(
    question: str,
    norm_question: str,
    occurrences: list[MetricOccurrence],
    median_spans: list[tuple[int, int]],
    aggregation: str,
    agg_pos: int,
    tickers: list[str],
    years: list[int],
) -> str:
    """Why this question cannot be answered as a one-year filter -> aggregate.

    Every check here is a clause the plan shape has no slot for. Dropping such a
    clause does not degrade the answer, it changes the question -- and unlike a
    decline, a confidently wrong catalog number also displaces the codegen
    attempt. So each returns a reason and the caller fails closed.
    """
    return (
        _scenario_adjustment(norm_question)
        or _subgroup_diff(norm_question)
        or _unconsumed_comparator(norm_question, median_spans)
        or _unnamed_sign_condition(norm_question, occurrences)
        or _composite_metric(norm_question, occurrences)
        or _multi_year_scope(norm_question, years)
        or _unmentioned_group_members(question, tickers)
        or _conditioned_share_denominator(norm_question, aggregation, agg_pos)
    )


def _aggregate_plan(
    state: Mapping[str, Any],
    question: str,
    norm_question: str,
    occurrences: list[MetricOccurrence],
    tickers: list[str],
    years: list[int],
) -> StructuredPlan:
    """Build a filter -> aggregate plan for a question with no max/min marker."""
    filters, median_spans = _all_filters(occurrences, norm_question, len(norm_question))
    if not filters:
        return StructuredPlan(
            supported=False, operation="unsupported", reason=_NO_GROUP_FILTER,
        )
    aggregation, agg_pos = _aggregation(norm_question, median_spans)
    if not aggregation:
        return StructuredPlan(
            supported=False, operation="unsupported", reason="no aggregation over the filtered group",
        )
    blocked = _unexpressible(
        question, norm_question, occurrences, median_spans,
        aggregation, agg_pos, tickers, years,
    )
    if blocked:
        return StructuredPlan(supported=False, operation="unsupported", reason=blocked)

    target = _target_unit(state, question)
    answer = ""
    if aggregation != "count":
        answer = _closest_metric(
            occurrences,
            agg_pos,
            exclude={flt.metric for flt in filters},
            target_unit="" if aggregation == "share" else target,
        )
        if not answer:
            return StructuredPlan(
                supported=False,
                operation="unsupported",
                reason="could not link the aggregated answer metric",
            )
    return StructuredPlan(
        supported=True,
        operation="filter_aggregate",
        aggregation=aggregation,
        axis="ticker",
        tickers=tickers,
        years=years,
        doc_type=str(state.get("doc_type") or "unknown"),
        answer_metric=answer,
        filters=filters,
        target_unit=target,
    )


def deterministic_selection_plan(state: Mapping[str, Any]) -> StructuredPlan:
    """Build a catalog-backed selection plan, or an unsupported plan."""
    question = str(state.get("question") or "")
    norm_question = _norm(question)
    order, marker_pos, order_reason = _selection_order(norm_question)

    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    years = sorted({int(y) for y in (state.get("years") or []) if y})
    occurrences = _metric_occurrences(question)

    if not order:
        # No extremum to rank by. The question may still filter a group and then
        # aggregate the survivors, which the same executor covers.
        if len(tickers) >= 2 and len(years) == 1 and occurrences:
            plan = _aggregate_plan(
                state, question, norm_question, occurrences, tickers, years,
            )
            # Report the aggregate branch's own reason rather than the generic
            # "no max/min" whenever the question did read as a group filter --
            # otherwise every aggregate near-miss is indistinguishable from a
            # question that is simply not a selection at all.
            if plan.supported or plan.reason != _NO_GROUP_FILTER:
                return plan
        return StructuredPlan(supported=False, operation="unsupported", reason=order_reason)

    axis, reason = _selection_axis(tickers, years)
    if not axis:
        return StructuredPlan(supported=False, operation="unsupported", reason=reason)

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
