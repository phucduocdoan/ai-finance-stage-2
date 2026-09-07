"""Raw-table selection request building.

Parses a state/question into a `RawLinkRequest` scoped to the selection axis
(year or ticker), the rank order (max/min), and the answer kind. Pure
request-side logic -- no candidate scoring or decision-making here.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Mapping, Sequence

from finance_qa.modules.solve.common.intent import (
    FILTER_MARKER as _FILTER_MARKER,
    MAX_MARKER as _MAX_MARKER,
    MIN_MARKER as _MIN_MARKER,
    TICKER_ANSWER_MARKER as _TICKER_ANSWER,
    YEAR_ANSWER_MARKER as _YEAR_ANSWER,
    norm as _norm,
)
from finance_qa.modules.solve.common.solution import Unit
from finance_qa.modules.solve.common.units import unit_from_hint
from finance_qa.modules.solve.solvers import raw_table_linker as raw
from finance_qa.modules.solve.solvers.cell_locator import period_intent, value_transform
from finance_qa.modules.solve.solvers.table_profiles.link_schema import RawLinkRequest, RawScopeSlot


SelectionAxis = Literal["year", "ticker"]
SelectionOrder = Literal["max", "min"]
SelectionAnswerKind = Literal["selected_value", "answer_value", "selected_year"]

_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b")
_VERBAL_RANGE = re.compile(r"\btu\s+nam\s+((?:19|20)\d{2}).{0,30}?\bden\s+nam\s+((?:19|20)\d{2})\b")


def _target_unit(state: Mapping[str, Any], question: str, answer_kind: str) -> Unit:
    unit = unit_from_hint(question) or unit_from_hint(str(state.get("unit_hint") or ""))
    if unit:
        return unit  # type: ignore[return-value]
    if answer_kind == "selected_year":
        return "year"
    return "unknown"


def _selection_order(question: str) -> tuple[SelectionOrder | None, str]:
    norm = _norm(question)
    max_match = _MAX_MARKER.search(norm)
    min_match = _MIN_MARKER.search(norm)
    if not max_match and not min_match:
        return None, "no max/min selection marker"
    if max_match and (not min_match or max_match.start() <= min_match.start()):
        return "max", ""
    return "min", ""


def _axis(tickers: Sequence[str], years: Sequence[int]) -> tuple[SelectionAxis | None, str]:
    if len(tickers) == 1 and len(years) >= 2:
        return "year", ""
    if len(tickers) >= 2 and len(years) == 1:
        return "ticker", ""
    if len(tickers) >= 2 and len(years) >= 2:
        return None, "multi-axis raw selection is not supported"
    return None, "selection needs one varying axis"


def _years_from_question(question: str) -> list[int]:
    match = _RANGE.search(question) or _VERBAL_RANGE.search(_norm(question))
    if match:
        first, last = int(match.group(1)), int(match.group(2))
        if first <= last and last - first <= 10:
            return list(range(first, last + 1))
    return sorted({int(year) for year in _YEAR.findall(question)})


def _answer_kind(question: str, axis: SelectionAxis, target_hint: str | None) -> tuple[SelectionAnswerKind | None, str]:
    norm = _norm(question)
    if axis == "ticker" and _TICKER_ANSWER.search(norm):
        return None, "selected ticker answer is not numeric"
    if axis == "year" and _YEAR_ANSWER.search(norm) and not target_hint:
        return "selected_year", ""
    if target_hint:
        return "answer_value", ""
    return "selected_value", ""


def build_request(
    state: Mapping[str, Any],
) -> tuple[RawLinkRequest | None, SelectionAxis | None, SelectionOrder | None, SelectionAnswerKind | None, str]:
    """Build a raw-table selection request, or a fail-closed reason."""
    question = str(state.get("question") or "")
    if _FILTER_MARKER.search(_norm(question)):
        return None, None, None, None, "conditional filter is outside raw_selection_linker"

    order, reason = _selection_order(question)
    if not order:
        return None, None, None, None, reason

    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    state_years = sorted({int(y) for y in (state.get("years") or []) if y})
    text_years = _years_from_question(question)
    years = text_years if len(text_years) >= 2 else state_years
    axis, reason = _axis(tickers, years)
    if not axis:
        return None, None, None, None, reason

    target_hint = unit_from_hint(question) or unit_from_hint(str(state.get("unit_hint") or ""))
    answer_kind, reason = _answer_kind(question, axis, target_hint)
    if not answer_kind:
        return None, None, None, None, reason

    slots = (
        [RawScopeSlot(ticker=tickers[0], year=year) for year in years]
        if axis == "year"
        else [RawScopeSlot(ticker=ticker, year=years[0]) for ticker in tickers]
    )
    if len(slots) > 8:
        return None, None, None, None, "too many raw selection slots"

    doc_type = str(state.get("doc_type") or "unknown")
    if doc_type not in {"consolidated", "separate"}:
        doc_type = "unknown"
    request = RawLinkRequest(
        operation="select",
        slots=slots,
        doc_type=doc_type,  # type: ignore[arg-type]
        period=period_intent(question),
        value_transform=value_transform(question, [question]),
        target_unit=_target_unit(state, question, answer_kind),
        query_norm=raw._norm(question),
        query_tokens=raw._tokens(question),
        identity_tokens=raw._scope_identity_tokens(slots, doc_type),
        wants_total=raw._wants_total(question),
    )
    return request, axis, order, answer_kind, ""
