"""Text normalization and scoring helpers for raw-table linking."""
from __future__ import annotations

import ast
import math
import re
from typing import Any, Mapping, Sequence

import pandas as pd

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.columns import column_years
from finance_qa.modules.solve.common.context import meta_for
from finance_qa.modules.solve.common.intent import norm as _norm
from finance_qa.modules.solve.solvers.cell_locator import PeriodIntent, _rank_bonus
from finance_qa.modules.solve.solvers.raw_table_linking.request import _tokens
from finance_qa.modules.solve.solvers.table_profiles.schema import RawLinkRequest
from finance_qa.modules.tools.numeric import parse_number


_YEAR = re.compile(r"(?:19|20)\d{2}")
_TOTAL_ROW = re.compile(r"^(?:cong|tong|tong\s+cong|cong\s+so|total)$")
_GENERIC_PERIOD_ROW = re.compile(
    r"^(?:so\s+du\s+)?(?:cuoi|dau)\s+(?:nam|ky)$|^nam\s+(?:nay|truoc)$|^ky\s+(?:nay|truoc)$"
)
# `Số cuối năm` and `Số đầu năm` also say nothing but the period, so they need the
# same tie-break; they are listed separately because they must not be dropped.
_PERIOD_ONLY_ROW = re.compile(
    r"^(?:so\s+(?:du\s+)?)?(?:cuoi|dau)\s+(?:nam|ky)$|^nam\s+(?:nay|truoc)$|^ky\s+(?:nay|truoc)$"
)
_COMPONENT_ROW = re.compile(r"^\s*-|trong\s+do", re.I)
_CURRENT_COL = re.compile(r"cuoi\s*(?:nam|ky)|nam\s+nay|ky\s+nay|31\s*12|31/12")
_PRIOR_COL = re.compile(r"dau\s*(?:nam|ky)|nam\s+truoc|ky\s+truoc|01\s*01|01/01|1\s+1")
_FLOW_QUESTION = re.compile(
    r"\b(?:phat\s+sinh\s+trong\s+(?:nam|ky)|phai\s+nop\s+trong\s+nam)\b"
)
_FLOW_COL = re.compile(r"\bphat\s+sinh\s+trong\s+(?:nam|ky)\b")
_BALANCE_COL = re.compile(r"\b(?:so\s+du|cuoi\s+(?:nam|ky)|31\s*12|31/12|31\.12)\b")
_PERCENT_COLUMN = re.compile(r"\bty\s+le\b|\bphan\s+tram\b")
_MONEY_UNITS = frozenset(
    {"vnd", "thousand_vnd", "million_vnd", "billion_vnd", "hundred_billion_vnd", "trillion_vnd"}
)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, (list, tuple)):
                return [_text(item) for item in parsed if _text(item)]
        return [raw]
    return [_text(value)] if _text(value) else []


def _token_score(
    query_tokens: Sequence[str], target: object, *, partial_query: bool = False
) -> float:
    """Overlap between a query and one label. `partial_query` when the query side is a
    deliberate fragment, such as one row phrase out of a search plan, rather than a
    whole question that ought to account for the label."""
    target_tokens = set(_tokens(target))
    if not query_tokens or not target_tokens:
        return 0.0
    matched = sum(1 for token in set(query_tokens) if token in target_tokens)
    # Long finance questions carry company names and units; dividing by all query
    # tokens would bury a good row-label hit. Use the smaller side as the ceiling.
    #
    # Floor that ceiling at three words. With a bare `min`, a one-word row scores a
    # perfect 1.0 off a single shared token and ties a six-word exact hit: `Tiền`
    # matched `tiến` from "phải thu theo tiến độ" and drew level with the gold row.
    ceiling = min(len(set(query_tokens)), max(len(target_tokens), 3))
    coverage = min(matched / max(1, ceiling), 1.0)
    if partial_query:
        return coverage
    # Charge for the words the label uses that the question never mentioned. An
    # aggregated line (`Khấu hao tài sản cố định và bất động sản đầu tư`) shares every
    # word of a question about investment property alone and so ties the specific note
    # row (`Trích khấu hao trong năm`), even though it answers something wider.
    unexplained = (len(target_tokens) - matched) / len(target_tokens)
    return coverage * (1.0 - 0.5 * unexplained)


def _semantic_score(
    query_tokens: Sequence[str], query_norm: str, target: object, *, partial_query: bool = False
) -> float:
    score = _token_score(query_tokens, target, partial_query=partial_query)
    target_tokens = _tokens(target)
    if not target_tokens:
        return score
    for size, value in ((4, 0.92), (3, 0.84), (2, 0.62)):
        if len(target_tokens) < size:
            continue
        for start in range(0, len(target_tokens) - size + 1):
            phrase = " ".join(target_tokens[start:start + size])
            if phrase in query_norm:
                score = max(score, value)
    return min(score, 1.0)


def _scoring_query_for_table(
    request: RawLinkRequest,
    table_id: str,
    *,
    meta_lookup=meta_for,
) -> tuple[list[str], str]:
    """Remove already-resolved entity identity from semantic row/table scoring.

    The raw linker only scans tables after ticker/year/doc_type scope filtering,
    so company-name tokens should not make a table or row look more relevant.
    """
    meta = meta_lookup(table_id)
    drop = set(request.identity_tokens)
    drop.update(_tokens(meta.get("company_name") or ""))
    ticker = _norm(meta.get("ticker") or "")
    if ticker:
        drop.add(ticker)
    tokens = [token for token in request.query_tokens if token not in drop]
    if not tokens:
        tokens = list(request.query_tokens)
    return tokens, " ".join(tokens)


def _labels_a_row(label: str) -> bool:
    """Whether a row label is wording at all rather than a misparsed number.

    Some tables are read with a numeric column as the label column, so the `row
    label` is `172.712.731.397`. Such a row names no metric and must not inherit
    the wording of the section above it.
    """
    return any(len(word) > 1 for word in re.findall(r"[a-z]+", _norm(label)))


def _row_text(label: str, path: Sequence[str] | None = None) -> str:
    """The scoreable wording of a row: its section ancestors plus its own label."""
    if not _labels_a_row(label):
        return label
    pieces = [*(path or []), label]
    return " > ".join(piece for piece in pieces if piece)


def _is_total_row(label: str) -> bool:
    norm = _norm(label)
    return bool(_TOTAL_ROW.fullmatch(norm)) or norm in {"cong", "tong cong"}


def _component_role_from_text(text: str, *, is_total: bool = False) -> str:
    if is_total or re.search(r"\b(?:tong\s+cong|tong|cong|total)\b", text):
        return "total"
    if re.search(r"\b(?:ngan\s+han|duoi\s+(?:1|mot)\s+nam|duoi\s+12\s+thang|den\s+12\s+thang)\b", text):
        return "lt_1y"
    if re.search(r"\b(?:trung\s+han|1\s+(?:toi|den)\s+5\s+nam|tu\s+tren\s+1\s+nam\s+den\s+5\s+nam)\b", text):
        return "1_to_5y"
    if re.search(r"\b(?:dai\s+han|tren\s+5\s+nam)\b", text):
        return "gt_5y"
    return ""


def _is_generic_period_row(label: str) -> bool:
    return bool(_GENERIC_PERIOD_ROW.fullmatch(_norm(label)))


def _generic_period_row_score(label: str, period: PeriodIntent) -> float:
    norm = _norm(label)
    if period in {"current", "annual", "unknown"} and re.search(r"\bcuoi\s+(?:nam|ky)\b", norm):
        return 0.52
    if period == "prior" and re.search(r"\bdau\s+(?:nam|ky)\b", norm):
        return 0.52
    return 0.0


def _row_period_adjustment(label: str, period: PeriodIntent) -> float:
    """Separate `Số cuối năm` from `Số đầu năm` when the leaf says only the period.

    Such a row is scored on its section ancestors, which its sibling shares, so
    the period wording in the leaf is the only thing that can tell them apart.

    This reads a wider set of labels than `_is_generic_period_row`, which also
    decides whether a row is dropped entirely: `Số cuối năm` needs the tie-break
    but must keep reaching the candidate surface on its own.
    """
    if not _PERIOD_ONLY_ROW.fullmatch(_norm(label)):
        return 0.0
    norm = _norm(label)
    current = bool(_CURRENT_COL.search(norm))
    prior = bool(_PRIOR_COL.search(norm))
    if period in {"current", "annual", "unknown"}:
        return 0.18 if current else (-0.24 if prior else 0.0)
    if period == "prior":
        return 0.18 if prior else (-0.24 if current else 0.0)
    return 0.0


def _is_component_row(label: str) -> bool:
    return bool(_COMPONENT_ROW.search(label))


def _is_percent_column(column: object) -> bool:
    """A share-of-total column. `_norm` drops the sign, so `%` is checked on the raw text."""
    return "%" in str(column) or bool(_PERCENT_COLUMN.search(_norm(column)))


def _column_year(
    column: object,
    table_id: str,
    meta_year: object,
    *,
    frame_loader=load_frame,
) -> int | None:
    text = str(column)
    match = _YEAR.search(text)
    if match:
        return int(match.group(0))
    inferred = column_years(frame_loader(table_id), table_id, meta_year).get(column)
    return int(inferred) if str(inferred or "").isdigit() else None


def _leaf(column: object) -> str:
    return str(column).split("|")[-1].strip()


def _column_score(
    column: object,
    *,
    slot_year: int,
    period: PeriodIntent,
    table_year: int | None,
    resolved_year: int | None = None,
) -> float:
    text = _norm(column)
    leaf = _norm(_leaf(column))
    score = 0.0
    explicit = _YEAR.search(text)
    if explicit and int(explicit.group(0)) == slot_year:
        score += 0.5
    elif resolved_year is not None and resolved_year == slot_year:
        # `Tại ngày 31 tháng 12 năm` lost its year at the OCR line break; the
        # period wording plus the report year put it back. That is the same
        # evidence as a printed year, so it earns the same credit.
        score += 0.5
    elif table_year == slot_year and not explicit:
        score += 0.12

    current_hit = bool(_CURRENT_COL.search(text))
    prior_hit = bool(_PRIOR_COL.search(text))
    current_leaf = bool(_CURRENT_COL.search(leaf))
    prior_leaf = bool(_PRIOR_COL.search(leaf))
    if period in {"current", "annual", "unknown"}:
        if current_leaf:
            score += 0.42
        elif current_hit:
            score += 0.24
        if prior_leaf:
            score -= 0.3
        elif prior_hit:
            score -= 0.12
    elif period == "prior":
        if prior_leaf:
            score += 0.42
        elif prior_hit:
            score += 0.24
        if current_leaf:
            score -= 0.12
    return max(0.0, min(score, 1.0))


def _flow_column_adjustment(request: RawLinkRequest, column: object) -> float:
    if not _FLOW_QUESTION.search(request.query_norm):
        return 0.0
    text = _norm(column)
    if _FLOW_COL.search(text):
        return 0.56
    if _BALANCE_COL.search(text):
        return -0.46
    return 0.0


def _safe_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(float(value)) else None
    return parse_number(str(value))


def _row_has_numeric_value(row: pd.Series, label_col: object) -> bool:
    return any(
        column != label_col and _safe_number(row[column]) is not None
        for column in row.index
    )


def _format_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6g}"


def _page_context_hint(meta: Mapping[str, Any], max_chars: int = 520) -> str:
    text = " ".join(_text(meta.get("context_page_text")).split())
    if not text:
        return ""
    company = _text(meta.get("company_name"))
    if company:
        text = text.replace(company, "").strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:].strip()


def _table_context(meta: Mapping[str, Any], profile_rows: Sequence[str]) -> str:
    pieces: list[str] = []
    for key in ("section_title", "note_title", "header_flat"):
        if meta.get(key):
            pieces.append(str(meta[key]))
    page_hint = _page_context_hint(meta)
    if page_hint:
        pieces.append(page_hint)
    labels = _text_list(meta.get("first_col_labels"))
    if labels:
        pieces.extend(str(label) for label in labels[:24])
    pieces.extend(profile_rows[:24])
    if meta.get("company_name"):
        pieces.append(str(meta["company_name"]))
    return " | ".join(piece for piece in pieces if piece)


def _short_context(text: str, max_chars: int = 220) -> str:
    return " ".join(text.split())[:max_chars]


__all__ = [
    "_BALANCE_COL",
    "_CURRENT_COL",
    "_FLOW_COL",
    "_FLOW_QUESTION",
    "_MONEY_UNITS",
    "_PRIOR_COL",
    "_YEAR",
    "_column_score",
    "_column_year",
    "_component_role_from_text",
    "_flow_column_adjustment",
    "_format_value",
    "_generic_period_row_score",
    "_is_component_row",
    "_is_generic_period_row",
    "_is_percent_column",
    "_is_total_row",
    "_labels_a_row",
    "_leaf",
    "_page_context_hint",
    "_rank_bonus",
    "_row_has_numeric_value",
    "_row_period_adjustment",
    "_row_text",
    "_safe_number",
    "_scoring_query_for_table",
    "_semantic_score",
    "_short_context",
    "_table_context",
    "_text",
    "_text_list",
    "_token_score",
]
