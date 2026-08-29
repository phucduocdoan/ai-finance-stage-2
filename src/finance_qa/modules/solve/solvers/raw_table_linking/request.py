"""Request inference and cheap gates for the raw-table linker."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from finance_qa.modules.rag.retrievers.filters import SCOPE_FREE_DOC_TYPES
from finance_qa.modules.solve.common.context import meta_for, table_metadata
from finance_qa.modules.solve.common.intent import (
    CONDITIONAL_FILTER_CUE as _CONDITIONAL_FILTER,
    DIFF_CUE_LOOSE as _DIFF,
    AVG_CUE as _AVG,
    MULTIPLIER_RATIO_CUE as _MULTIPLIER_RATIO,
    RATIO_CUE as _RATIO,
    SELECTION_MARKER as _SELECTION,
    SUM_CUE as _SUM,
    intent_norm as _intent_norm,
    norm as _norm,
)
from finance_qa.modules.solve.common.units import unit_from_hint
from finance_qa.modules.solve.solvers.cell_locator import period_intent, value_transform
from finance_qa.modules.solve.solvers.table_profiles.schema import (
    RawLinkRequest,
    RawOperation,
    RawScopeSlot,
)


_TOTAL_QUESTION = re.compile(r"\b(?:tong\s+so\s+du|tong\s+gia\s+tri|tong\s+du\s+no|tong\s+cong)\b")
_STOPWORDS = {
    "a", "an", "and", "bao", "bao nhieu", "bang", "bao cao", "bctc",
    "cai", "cac", "cho", "co", "cong", "cong ty", "cp", "ctcp", "cua",
    "cuoi", "den", "diem", "don", "don vi", "duoc", "giua", "hoi",
    # `ngan` is deliberately absent: it was here for `ngân hàng`, but stripping it
    # also deletes `ngắn` from every row label, so `Ngắn hạn` and `Dài hạn` become
    # the same word. Bank names are dropped per table by `_scoring_query_for_table`.
    "hop", "la", "me", "muc", "nam", "ngan hang", "phan", "rieng",
    "so", "tai", "tap", "tap doan", "theo", "thoi", "tinh", "tmcp", "trong",
    "ty", "va", "vao", "viet", "viet nam", "vnd",
}
_UNIT_TOKENS = {
    "dong", "trieu", "nghin", "tram", "vnd", "vnd", "phan", "tram",
    "co", "lan",
}


def _tokens(text: object) -> list[str]:
    out: list[str] = []
    for token in _norm(text).split():
        if token.isdigit() or token in _STOPWORDS or token in _UNIT_TOKENS:
            continue
        if len(token) <= 1:
            continue
        out.append(token)
    return out


def _wants_total(question: str) -> bool:
    return bool(_TOTAL_QUESTION.search(_intent_norm(question)))


def _scope_slots(tickers: Sequence[str], years: Sequence[int], operation: RawOperation) -> list[RawScopeSlot]:
    tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
    years = [int(y) for y in years if y]
    if operation == "diff":
        if len(tickers) == 2 and len(years) == 1:
            return [RawScopeSlot(ticker=ticker, year=years[0]) for ticker in tickers]
        if len(tickers) == 1 and len(years) == 2:
            ordered_years = sorted(years, reverse=True)
            return [RawScopeSlot(ticker=tickers[0], year=year) for year in ordered_years]
    if len(tickers) == 1 and len(years) >= 1:
        return [RawScopeSlot(ticker=tickers[0], year=year) for year in sorted(set(years))]
    if len(years) == 1 and len(tickers) >= 1:
        return [RawScopeSlot(ticker=ticker, year=years[0]) for ticker in tickers]
    return []


def _has_component_ratio_intent(norm_question: str) -> bool:
    return bool(_RATIO.search(norm_question) or _MULTIPLIER_RATIO.search(norm_question))


def _is_cross_company_sum(norm_question: str, tickers: Sequence[str]) -> bool:
    """`Tổng <chỉ tiêu> của A, B và C` is a sum even when `SUM_CUE` misses the metric.

    `SUM_CUE` is a whitelist of metric phrases (`tong gia tri`, `tong doanh thu`, ...),
    so `Tổng chi phí tài chính của` five named companies falls out of it and the whole
    request is refused with `outside raw-table fixed-scope operations`. That refusal
    sends the question to codegen, which then writes a query over whichever single
    table it was handed: q862 asks about five companies and shipped one CSV.

    The guard is three or more tickers, not two. With two, `tickers` picks up name
    variants of one company (q651 resolves `CTCP Masan MeatLife` to two codes) and the
    question is a growth rate, not a sum, so `tong` there belongs to the line item
    name. Three named companies plus a bare `tong` has no such reading. Measured over
    all 1,012 questions this changes exactly six: 848, 862, 915, 922, 964, 1003.

    `_AVG` and `_DIFF` are tested before this, so `trung binh`/`chenh lech` phrasings
    keep their own operation.
    """
    return len(tickers) >= 3 and bool(re.search(r"\btong\b", norm_question))


def _infer_operation(question: str, tickers: Sequence[str], years: Sequence[int]) -> RawOperation | None:
    norm = _intent_norm(question)
    if _SELECTION.search(norm) or _CONDITIONAL_FILTER.search(norm):
        return None
    if _has_component_ratio_intent(norm):
        return "ratio"
    if _AVG.search(norm):
        return "avg"
    if _DIFF.search(norm):
        return "diff"
    if _SUM.search(norm) or _is_cross_company_sum(norm, tickers):
        return "sum"
    if _RATIO.search(norm):
        return "ratio"
    if len(tickers) == 1 and len(years) == 1:
        return "direct"
    return None


def _scope_ok(
    table_id: str,
    slot: RawScopeSlot,
    doc_type: str,
    *,
    meta_lookup=meta_for,
) -> bool:
    meta = meta_lookup(table_id)
    if str(meta.get("ticker") or "").upper() != slot.ticker:
        return False
    if str(meta.get("year") or "") != str(slot.year):
        return False
    if doc_type in {"consolidated", "separate"} and str(meta.get("doc_type") or "") != doc_type:
        return False
    return True


def _scope_table_ids(
    slot: RawScopeSlot,
    doc_type: str,
    *,
    metadata_lookup=table_metadata,
) -> list[str]:
    """Table ids in scope for one (ticker, year) slot.

    When `doc_type == "unknown"`, this mirrors `prefer_consolidated` (see
    `rag/retrievers/filters.py`): a `separate` table is dropped once a broader-scope
    table (`consolidated` / `aggregated` / `explanations`) also matches, since it re-
    queries the full metadata table and would otherwise re-admit the `separate` table
    that the RAG-shortlist stage had already excluded for the same slot.
    """
    matches: list[tuple[str, str]] = []
    for table_id, meta in metadata_lookup().items():
        if str(meta.get("ticker") or "").upper() != slot.ticker:
            continue
        if str(meta.get("year") or "") != str(slot.year):
            continue
        table_doc_type = str(meta.get("doc_type") or "")
        if doc_type in {"consolidated", "separate"} and table_doc_type != doc_type:
            continue
        matches.append((table_id, table_doc_type))
    if doc_type == "unknown" and any(t in {"consolidated", *SCOPE_FREE_DOC_TYPES} for _, t in matches):
        matches = [(table_id, t) for table_id, t in matches if t != "separate"]
    return [table_id for table_id, _ in matches]


def _scope_identity_tokens(
    slots: Sequence[RawScopeSlot],
    doc_type: str,
    *,
    meta_lookup=meta_for,
    metadata_lookup=table_metadata,
) -> list[str]:
    tokens: set[str] = set()
    for slot in slots:
        tokens.update(_tokens(slot.ticker))
        for table_id in _scope_table_ids(slot, doc_type, metadata_lookup=metadata_lookup):
            company_name = meta_lookup(table_id).get("company_name")
            if company_name:
                tokens.update(_tokens(company_name))
                break
    return sorted(tokens)


def build_request(
    state: Mapping[str, Any],
    *,
    meta_lookup=meta_for,
    metadata_lookup=table_metadata,
) -> tuple[RawLinkRequest | None, str]:
    """Cheap fail-closed gate before scanning raw tables or calling the planner."""
    question = str(state.get("question") or "")
    tickers = [str(t).upper().strip() for t in (state.get("tickers") or []) if str(t).strip()]
    years = [int(y) for y in (state.get("years") or []) if y]
    if not tickers or not years:
        return None, "needs resolved ticker/year scope"
    unit = unit_from_hint(question) or unit_from_hint(str(state.get("unit_hint") or "")) or "unknown"
    operation = _infer_operation(question, tickers, years)
    if operation == "direct" and unit == "ratio" and _MULTIPLIER_RATIO.search(_norm(question)):
        operation = "ratio"
    if operation is None:
        return None, "outside raw-table fixed-scope operations"
    slots = _scope_slots(tickers, years, operation)
    if not slots:
        return None, "scope shape is not supported"
    if operation in {"sum", "avg"} and len(slots) == 1:
        return None, f"single-slot {operation} is a lookup, not raw-table arithmetic"
    if len(slots) > 8:
        return None, "too many raw-table slots"
    if operation == "direct" and (bool(state.get("multi_year")) or bool(state.get("multi_company"))):
        return None, "direct operation cannot be multi-axis"

    if operation == "direct" and unit == "ratio":
        return None, "single-cell direct request cannot answer a ratio"
    doc_type = str(state.get("doc_type") or "unknown")
    if doc_type not in {"consolidated", "separate"}:
        doc_type = "unknown"
    query_tokens = _tokens(question)
    identity_tokens = _scope_identity_tokens(
        slots,
        doc_type,
        meta_lookup=meta_lookup,
        metadata_lookup=metadata_lookup,
    )
    return RawLinkRequest(
        operation=operation,
        slots=slots,
        doc_type=doc_type,  # type: ignore[arg-type]
        period=period_intent(question),
        value_transform=value_transform(question, [question]),
        target_unit=unit,  # type: ignore[arg-type]
        query_norm=_norm(question),
        query_tokens=query_tokens,
        identity_tokens=identity_tokens,
        wants_total=_wants_total(question),
        ratio_aggregate="avg" if operation == "ratio" and _AVG.search(_norm(question)) and len(slots) > 1 else "none",
    ), ""


def should_attempt_raw_table_linker(
    state: Mapping[str, Any],
    *,
    meta_lookup=meta_for,
    metadata_lookup=table_metadata,
) -> tuple[bool, str]:
    request, reason = build_request(
        state,
        meta_lookup=meta_lookup,
        metadata_lookup=metadata_lookup,
    )
    return (request is not None), reason


__all__ = [
    "build_request",
    "should_attempt_raw_table_linker",
    "_scope_identity_tokens",
    "_scope_ok",
    "_scope_table_ids",
    "_tokens",
    "_wants_total",
]
