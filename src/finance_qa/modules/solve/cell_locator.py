"""Deterministic single-cell locator for simple lookup questions.

This module is intentionally narrower than `codegen`: it only handles questions
that already look like one ticker, one year, one value. The LLM has already done
semantic extraction in the understand node; this code turns that intent into a
specific row/column only when the evidence is unambiguous.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Literal, Mapping, Sequence

import pandas as pd
from pydantic import BaseModel, Field

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen import PandasSolution, Unit
from finance_qa.modules.solve.columns import column_years, money_columns
from finance_qa.modules.solve.context import meta_for, page_text
from finance_qa.modules.solve.lookup import RowHit, search_rows
from finance_qa.modules.solve.units import detect_unit, unit_from_hint

PeriodIntent = Literal["annual", "current", "prior", "unknown"]
ValueTransform = Literal["as_reported", "abs"]

_NON_WORD = re.compile(r"[^a-z0-9]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_CURRENT_PERIOD = re.compile(
    r"cu[oố]i\s*(?:n[aă]m|k[yỳ])|(?<!\d)31\s*/\s*12(?!\d)|31\s*th[aá]ng\s*12|"
    r"t[aạ]i\s+ng[aà]y|[đd][eế]n\s+ng[aà]y|n[aă]m\s+nay|k[yỳ]\s+n[aà]y",
    re.I,
)
_PRIOR_PERIOD = re.compile(
    r"[đd][aầ]u\s*(?:n[aă]m|k[yỳ])|(?<!\d)0?1\s*/\s*0?1(?!\d)|"
    r"1\s*th[aá]ng\s*1|n[aă]m\s+tr[uư][oớ]c|k[yỳ]\s+tr[uư][oớ]c",
    re.I,
)
_DERIVED_MARKER = re.compile(
    r"\b(?:roe|roa|d/e|cfo/lnst|cfo/dtt)\b|"
    r"t[ỷy]\s*(?:su[aấ]t|l[ệe]|s[oố]|tr[oọ]ng)|h[ệe]\s*s[oố]|bi[eê]n\s+l[ợo]i|"
    r"t[aă]ng\s+tr[uư][ởo]ng|ch[eê]nh\s+l[ệe]ch|cao\s+nh[aấ]t|th[aấ]p\s+nh[aấ]t|"
    r"l[ớo]n\s+nh[aấ]t|nh[oỏ]\s+nh[aấ]t|trung\s+b[iì]nh|b[iì]nh\s+qu[aâ]n",
    re.I,
)
_QUESTION_TAIL = re.compile(
    r"\s+(?:l[aà]|b[ằa]ng|đ[ạa]t)?\s*bao\s+nhi[eê]u\b.*$",
    re.I,
)
_LEADING_TIME = re.compile(r"^\s*(?:cu[oố]i\s+n[aă]m|n[aă]m|v[aà]o\s+n[aă]m)\s+\d{4},?\s*", re.I)
_SCOPE_MARKER = re.compile(
    r"\s+(?:c[uủ]a\s+(?:c[oô]ng\s+ty|ng[aâ]n\s+h[aà]ng|t[oổ]ng\s+c[oô]ng\s+ty|"
    r"t[ậa]p\s+[đd]o[aà]n|ctcp|[A-Z]{2,5}\b)|n[aă]m\s+\d{4}|"
    r"(?:cu[oố]i|[đd][aầ]u)\s+n[aă]m\s+\d{4}|"
    r"v[aà]o\s+(?:cu[oố]i|[đd][aầ]u|ng[aà]y)|"
    r"[đd][eế]n\s+ng[aà]y|t[aạ]i\s+ng[aà]y)\b",
    re.I,
)
_UNIT_WORDS = re.compile(
    r"\b(?:tri[eệ]u|t[ỷy]|ngh[iì]n|tr[aă]m|đ[oồ]ng|vnd|vnđ|c[oổ]\s*ph[iế]u|"
    r"c[oổ]\s*ph[aầ]n|%|ph[aầ]n\s*tr[aă]m)\b",
    re.I,
)
_MAGNITUDE_METRIC = re.compile(
    r"chi\s+ph[ií]|d[uự]\s+ph[oò]ng|hao\s+m[oò]n|kh[aấ]u\s+hao|l[aã]i\s+vay",
    re.I,
)
_SIGNED_METRIC = re.compile(
    r"l[uư]u\s+chuy[eể]n|d[oò]ng\s+ti[eề]n|l[aã]i\s*/\s*l[oỗ]|l[oỗ]\b|ch[eê]nh\s+l[ệe]ch",
    re.I,
)
_TOTAL_TOKEN = re.compile(r"\btong\b|\btong\s+cong\b")

_DIRECT_METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "revenue": ("Doanh thu thuần", "Doanh thu"),
    "net_revenue": ("Doanh thu thuần",),
    "gross_profit": ("Lợi nhuận gộp",),
    "net_profit": (
        "Lợi nhuận sau thuế thu nhập doanh nghiệp",
        "Lợi nhuận sau thuế",
    ),
    "profit_after_tax": (
        "Lợi nhuận sau thuế thu nhập doanh nghiệp",
        "Lợi nhuận sau thuế",
    ),
    "profit_before_tax": ("Lợi nhuận trước thuế",),
    "total_assets": ("Tổng cộng tài sản", "Tổng tài sản", "TÀI SẢN"),
    "assets": ("Tổng cộng tài sản", "Tổng tài sản", "TÀI SẢN"),
    "total_debt": ("Tổng nợ phải trả", "Nợ phải trả"),
    "liabilities": ("Tổng nợ phải trả", "Nợ phải trả"),
    "equity": ("Vốn chủ sở hữu", "Tổng vốn chủ sở hữu"),
    "interest_expense": ("Chi phí lãi vay", "Lãi vay"),
    "interest_income": ("Lãi tiền gửi", "Thu nhập lãi và các khoản thu nhập tương tự"),
    "net_cash_operating": (
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh (mã số 20)",
    ),
    "operating_cash_flow": (
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh (mã số 20)",
    ),
    "cash_and_equivalents": ("Tiền và các khoản tương đương tiền", "Tiền và tương đương tiền"),
    "inventory": ("Hàng tồn kho",),
    "current_assets": ("Tài sản ngắn hạn",),
    "current_liabilities": ("Nợ ngắn hạn", "Nợ phải trả ngắn hạn"),
    "share_capital": ("Vốn cổ phần", "Vốn điều lệ"),
    "shares": ("Tổng số lượng cổ phần", "Số lượng cổ phần"),
}


def _norm(text: object) -> str:
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def _unique(items: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = " ".join(str(item).split())
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


class CellRequest(BaseModel):
    """One semantic request for a direct table cell."""

    metric_phrases: list[str] = Field(default_factory=list)
    ticker: str = ""
    year: int = 0
    doc_type: Literal["consolidated", "separate", "unknown"] = "unknown"
    period: PeriodIntent = "unknown"
    value_transform: ValueTransform = "as_reported"
    target_unit: Unit = "unknown"


class CellHit(BaseModel):
    """One located cell and its executable query."""

    table_id: str
    row_position: int
    row_label: str
    column: str
    source_unit: Unit = "unknown"
    target_unit: Unit = "unknown"
    pandas_query: str
    confidence: float
    row_score: float
    column_score: float
    phrase: str
    reason: str = ""

    def solution(self, variable: str) -> PandasSolution:
        return PandasSolution(
            table_variable=variable,
            target_row=self.row_label,
            target_column=self.column,
            source_unit=self.source_unit,
            target_unit=self.target_unit,
            pandas_query=self.pandas_query.replace("df1.", f"{variable}.", 1)
            if variable != "df1" else self.pandas_query,
        )


def period_intent(question: str) -> PeriodIntent:
    """Snapshot/period hint in the question text."""
    if _PRIOR_PERIOD.search(question):
        return "prior"
    if _CURRENT_PERIOD.search(question):
        return "current"
    if _YEAR.search(question):
        return "annual"
    return "unknown"


def direct_metric_phrases(question: str, metric: str = "") -> list[str]:
    """Candidate row-label phrases from the question and the canonical metric key."""
    text = _QUESTION_TAIL.sub("", question)
    text = re.sub(r"\([^)]{1,12}\)", "", text)
    text = _LEADING_TIME.sub("", text)
    match = _SCOPE_MARKER.search(text)
    if match:
        text = text[: match.start()]
    text = _UNIT_WORDS.sub(" ", text)
    text = re.sub(r"\b(?:h[oợ]p\s+nh[aấ]t|c[oô]ng\s+ty\s+m[eẹ]|bctc|b[aá]o\s+c[aá]o)\b", " ", text, flags=re.I)
    phrase = " ".join(text.strip(" ?.,;:").split())

    labels: list[str] = []
    if phrase and len(_norm(phrase).split()) >= 2:
        labels.append(phrase)
    metric_key = _norm(metric).replace(" ", "_")
    aliases = _DIRECT_METRIC_LABELS.get(metric_key, ())
    norm_question = _norm(question)
    if labels:
        labels.extend(alias for alias in aliases if _norm(alias) in norm_question)
    else:
        labels.extend(aliases)
    if metric and len(_norm(metric).split()) >= 2:
        labels.append(metric)
    return _unique(labels)[:6]


def value_transform(question: str, metric_phrases: Sequence[str]) -> ValueTransform:
    """Whether a reported signed cell should answer as a magnitude.

    Expense/provision rows are often printed negative in income statements. A
    question asking "chi phí ... là bao nhiêu" normally asks for the amount, not
    for the accounting sign. Cash-flow and profit/loss wording stay signed.
    """
    text = " ".join([question, *metric_phrases])
    if _SIGNED_METRIC.search(text):
        return "as_reported"
    return "abs" if _MAGNITUDE_METRIC.search(text) else "as_reported"


def build_request(state: Mapping[str, Any]) -> tuple[CellRequest | None, str]:
    """Conservative L1 gate over the understood state."""
    question = str(state.get("question") or "")
    tickers = [str(t).upper() for t in (state.get("tickers") or []) if str(t).strip()]
    years = [int(y) for y in (state.get("years") or []) if y]
    if len(tickers) != 1 or len(years) != 1:
        return None, "needs exactly one ticker and one year"
    if bool(state.get("multi_year")) or bool(state.get("multi_company")):
        return None, "multi-axis question"
    if _DERIVED_MARKER.search(question):
        return None, "derived or comparison marker"
    if state.get("operation") not in {"", "lookup"} and state.get("answer_shape") != "single_cell":
        return None, "not a lookup-shaped question"

    phrases = direct_metric_phrases(question, str(state.get("metric") or ""))
    if not phrases:
        return None, "no metric phrase"
    return CellRequest(
        metric_phrases=phrases,
        ticker=tickers[0],
        year=years[0],
        doc_type=str(state.get("doc_type") or "unknown"),
        period=period_intent(question),
        value_transform=value_transform(question, phrases),
        target_unit=unit_from_hint(str(state.get("unit_hint") or ""))
        or unit_from_hint(question)
        or "unknown",
    ), ""


def _explicit_year(column: object) -> int | None:
    match = _YEAR.search(str(column))
    return int(match.group(0)) if match else None


def _period_column_score(column: object, *, period: PeriodIntent) -> float:
    text = str(column)
    if period == "current" and _CURRENT_PERIOD.search(text):
        return 2.0
    if period == "prior" and _PRIOR_PERIOD.search(text):
        return 2.0
    if period == "annual" and re.search(r"n[aă]m\s+nay|k[yỳ]\s+n[aà]y", text, re.I):
        return 1.2
    return 0.0


def _usable_numeric(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _column_choice(df: pd.DataFrame, table_id: str, row_position: int, request: CellRequest) -> tuple[str, float] | None:
    meta = meta_for(table_id)
    inferred = column_years(df, table_id, meta.get("year"))
    money = set(money_columns(df))
    row = df.iloc[row_position]
    candidates: list[tuple[float, int, str]] = []
    for order, column in enumerate(df.columns):
        if not _usable_numeric(row[column]):
            continue
        score = 0.0
        if column in money:
            score += 0.5
        explicit = _explicit_year(column)
        inferred_year = inferred.get(column)
        if explicit == request.year:
            score += 4.0
        elif inferred_year == str(request.year):
            score += 3.2
        elif request.period == "prior" and inferred_year == str(request.year - 1):
            score += 2.6
        score += _period_column_score(column, period=request.period)
        if not explicit and not inferred_year and str(meta.get("year") or "") == str(request.year):
            # For tables with two unlabeled numeric columns, `column_years` already
            # handles order. This is only a weak fallback for one-column notes.
            score += 0.8
        if score <= 0.0:
            continue
        candidates.append((score, order, str(column)))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.35:
        return None
    return candidates[0][2], min(candidates[0][0] / 5.5, 1.0)


def _source_unit(df: pd.DataFrame, table_id: str, column: str) -> Unit:
    unit, _ = detect_unit(df, column, page_text(table_id))
    return unit or "unknown"


def _rank_bonus(table_id: str, ranked_tables: Sequence[str]) -> float:
    try:
        rank = ranked_tables.index(table_id)
    except ValueError:
        return 0.0
    if rank < 3:
        return 0.08
    if rank < 10:
        return 0.04
    return 0.0


def _hit_to_cell(
    hit: RowHit,
    phrase: str,
    request: CellRequest,
    ranked_tables: Sequence[str],
) -> CellHit | None:
    if _TOTAL_TOKEN.search(_norm(phrase)) and not _TOTAL_TOKEN.search(_norm(hit.label)):
        return None
    try:
        df = load_frame(hit.table_id)
    except Exception:  # noqa: BLE001 - one unreadable table cannot answer
        return None
    if hit.position < 0 or hit.position >= len(df):
        return None
    choice = _column_choice(df, hit.table_id, hit.position, request)
    if choice is None:
        return None
    column, column_score = choice
    raw_query = f"df1.iloc[{hit.position}][{column!r}]"
    query = f"abs({raw_query})" if request.value_transform == "abs" else raw_query
    confidence = (
        min(hit.score, 1.0) * 0.58
        + column_score * 0.34
        + _rank_bonus(hit.table_id, ranked_tables)
    )
    return CellHit(
        table_id=hit.table_id,
        row_position=hit.position,
        row_label=hit.label,
        column=column,
        source_unit=_source_unit(df, hit.table_id, column),
        target_unit=request.target_unit,
        pandas_query=query,
        confidence=round(min(confidence, 1.0), 4),
        row_score=round(min(hit.score, 1.0), 4),
        column_score=round(column_score, 4),
        phrase=phrase,
    )


def locate_single_cell(
    state: Mapping[str, Any],
    *,
    table_ids: Sequence[str] | None = None,
    shortlist: Sequence[str] | None = None,
    threshold: float = 0.78,
) -> tuple[CellHit | None, dict[str, Any]]:
    """Return a high-confidence located cell, otherwise a fallback reason."""
    request, reason = build_request(state)
    if request is None:
        return None, {"done": False, "reason": reason}

    ranked = list(dict.fromkeys([*(table_ids or []), *(shortlist or [])]))
    if not ranked:
        return None, {"done": False, "reason": "no candidate tables", "request": request.model_dump()}

    cells: list[CellHit] = []
    for phrase in request.metric_phrases:
        hits = search_rows(ranked, phrase, ticker=request.ticker, year=request.year, limit=12)
        for hit in hits:
            cell = _hit_to_cell(hit, phrase, request, ranked)
            if cell is not None:
                cells.append(cell)

    if not cells:
        return None, {"done": False, "reason": "no located numeric cell", "request": request.model_dump()}
    deduped: dict[tuple[str, int, str], CellHit] = {}
    for cell in cells:
        key = (cell.table_id, cell.row_position, cell.column)
        if key not in deduped or cell.confidence > deduped[key].confidence:
            deduped[key] = cell
    cells = list(deduped.values())
    cells.sort(key=lambda h: (-h.confidence, -h.row_score, -h.column_score, h.table_id, h.row_position))
    best = cells[0]
    if best.confidence < threshold:
        return None, {
            "done": False,
            "reason": "below confidence threshold",
            "request": request.model_dump(),
            "best": best.model_dump(),
        }
    if len(cells) > 1 and best.confidence - cells[1].confidence < 0.04 and (
        best.table_id != cells[1].table_id
        or best.row_position != cells[1].row_position
        or best.column != cells[1].column
    ):
        return None, {
            "done": False,
            "reason": "ambiguous located cells",
            "request": request.model_dump(),
            "best": best.model_dump(),
            "runner_up": cells[1].model_dump(),
        }
    return best, {
        "done": True,
        "request": request.model_dump(),
        "hit": best.model_dump(),
        "candidate_count": len(cells),
    }


__all__ = [
    "CellHit",
    "CellRequest",
    "build_request",
    "direct_metric_phrases",
    "locate_single_cell",
    "period_intent",
]
