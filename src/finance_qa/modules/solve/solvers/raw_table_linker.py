"""Raw-table cell linker for fixed-scope arithmetic.

``long_format`` is a clean main-statement fact layer. This module covers the
next controlled slice: questions whose scope is already fixed, but whose facts
live in raw CSV tables, notes, bank layouts, or tables without VAS ``Mã số``.

The LLM does not write pandas. It only chooses from a bounded list of real cell
candidates and an operation. Python validates scope/unit/ambiguity and builds the
submitted expression.
"""
from __future__ import annotations

import ast
import math
import re
from typing import Any, Literal, Mapping, Sequence

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.columns import column_years
from finance_qa.modules.solve.common.context import meta_for, page_text, table_metadata
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
from finance_qa.modules.solve.common.lookup import label_column
from finance_qa.modules.solve.common.solution import STRUCTURED_METHOD, PandasSolution, Unit
from finance_qa.modules.solve.common.units import MONEY_SCALE, detect_unit, unit_from_hint
from finance_qa.modules.solve.facts.table_profile import build_table_profile
from finance_qa.modules.solve.solvers.cell_locator import PeriodIntent, period_intent, value_transform
from finance_qa.modules.solve.solvers.table_linking.columns import (
    build_column_group_candidates,
    build_column_profiles,
)
from finance_qa.modules.solve.solvers.table_linking.rows import build_row_profiles
from finance_qa.modules.solve.solvers.table_linking.schema import (
    RawCellCandidate,
    RawGroupCandidate,
    RawLinkRequest,
    RawLinkedCandidate,
    RawOperation,
    RawScopeSlot,
)
from finance_qa.modules.tools.numeric import parse_number


_YEAR = re.compile(r"(?:19|20)\d{2}")
_TOTAL_ROW = re.compile(r"^(?:cong|tong|tong\s+cong|cong\s+so|total)$")
_TOTAL_QUESTION = re.compile(r"\b(?:tong\s+so\s+du|tong\s+gia\s+tri|tong\s+du\s+no|tong\s+cong)\b")
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
_MIN_DIRECT_SCORE = 0.84
_NORMALIZED_UNSUPPORTED_REASON = "complete candidate_ids supplied despite unsupported:"


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _tokens(text: object) -> list[str]:
    out: list[str] = []
    for token in _norm(text).split():
        if token.isdigit() or token in _STOPWORDS or token in _UNIT_TOKENS:
            continue
        if len(token) <= 1:
            continue
        out.append(token)
    return out


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


def _rank_bonus(table_id: str, ranked: Sequence[str]) -> float:
    try:
        rank = ranked.index(table_id)
    except ValueError:
        return 0.0
    if rank < 3:
        return 0.08
    if rank < 10:
        return 0.04
    return 0.0


def _scoring_query_for_table(request: RawLinkRequest, table_id: str) -> tuple[list[str], str]:
    """Remove already-resolved entity identity from semantic row/table scoring.

    The raw linker only scans tables after ticker/year/doc_type scope filtering,
    so company-name tokens should not make a table or row look more relevant.
    """
    meta = meta_for(table_id)
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


_PERCENT_COLUMN = re.compile(r"\bty\s+le\b|\bphan\s+tram\b")
_MONEY_UNITS = frozenset(
    {"vnd", "thousand_vnd", "million_vnd", "billion_vnd", "hundred_billion_vnd", "trillion_vnd"}
)


def _is_percent_column(column: object) -> bool:
    """A share-of-total column. `_norm` drops the sign, so `%` is checked on the raw text."""
    return "%" in str(column) or bool(_PERCENT_COLUMN.search(_norm(column)))


def _wants_total(question: str) -> bool:
    return bool(_TOTAL_QUESTION.search(_intent_norm(question)))


def _column_year(column: object, table_id: str, meta_year: object) -> int | None:
    text = str(column)
    match = _YEAR.search(text)
    if match:
        return int(match.group(0))
    inferred = column_years(load_frame(table_id), table_id, meta_year).get(column)
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


class RawLinkerDecision(BaseModel):
    """LLM output: choose cells and an operation, not code."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when the candidates do not support the question.")
    operation: RawOperation = Field(default="direct")
    candidate_ids: list[str] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("candidate_ids", mode="before")
    @classmethod
    def _candidate_ids(cls, value):
        return [str(v).strip() for v in (value or []) if str(v).strip()]


class RawRatioSlotDecision(BaseModel):
    """LLM output for one scoped ratio: numerator cells over denominator cells."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    numerator_candidate_ids: list[str] = Field(default_factory=list)
    denominator_candidate_ids: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("numerator_candidate_ids", "denominator_candidate_ids", mode="before")
    @classmethod
    def _candidate_ids(cls, value):
        return [str(v).strip() for v in (value or []) if str(v).strip()]


class RawRatioDecision(BaseModel):
    """LLM output for ratio-from-components questions."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when candidates cannot express all numerator/denominator components.")
    operation: Literal["ratio"] = "ratio"
    slots: list[RawRatioSlotDecision] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class RawRatioOption(BaseModel):
    """One complete numerator or denominator option shown to the ratio planner."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slot_key: str
    side: Literal["numerator", "denominator"]
    candidate_ids: list[str] = Field(default_factory=list)
    source_kind: Literal["cell", "group"] = "cell"
    label: str = ""
    semantic_role: str = ""
    value: float = 0.0
    unit: Unit = "unknown"
    table_ids: list[str] = Field(default_factory=list)
    context: str = ""
    score: float = 0.0

    @field_validator("candidate_ids", "table_ids", mode="before")
    @classmethod
    def _string_list(cls, value):
        return [str(v).strip() for v in (value or []) if str(v).strip()]


class RawRatioOptionSlotDecision(BaseModel):
    """LLM output for one scoped ratio over pre-partitioned options."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    numerator_option_id: str
    denominator_option_id: str
    reason: str = ""


class RawRatioOptionDecision(BaseModel):
    """LLM output over ratio options, not raw mixed candidates."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when options cannot answer every slot.")
    operation: Literal["ratio"] = "ratio"
    slots: list[RawRatioOptionSlotDecision] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class RawSlotSemanticConstraint(BaseModel):
    """Semantic constraints for one required slot, emitted by the planner."""

    model_config = ConfigDict(extra="forbid")

    slot_key: str
    row_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that should appear in the candidate row label.",
    )
    context_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that should appear in table/note context.",
    )
    include_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that should appear in the correct row/column/table context.",
    )
    exclude_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that identify close-but-wrong candidates.",
    )
    prefer_total_row: bool = False
    requires_component_sum: bool = False

    @field_validator("row_phrases", "context_phrases", "include_phrases", "exclude_phrases", mode="before")
    @classmethod
    def _phrases(cls, value):
        seen: set[str] = set()
        out: list[str] = []
        for raw in value or []:
            phrase = str(raw).strip()
            norm = _norm(phrase)
            if not phrase or not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(phrase[:120])
        return out[:8]


class RawSemanticPlan(BaseModel):
    """Planner output: semantic constraints, not candidate ids or code."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when candidates do not contain enough semantic evidence.")
    operation: RawOperation = Field(default="direct")
    slots: list[RawSlotSemanticConstraint] = Field(default_factory=list)
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class RawSearchPlan(BaseModel):
    """Planner output before candidate building: semantic query expansion."""

    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(description="False when the question is too ambiguous for raw-table linking.")
    row_phrases: list[str] = Field(
        default_factory=list,
        description="Likely row-label phrases or discriminative row-label fragments.",
    )
    context_phrases: list[str] = Field(
        default_factory=list,
        description="Likely note/table context phrases.",
    )
    include_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases that can appear in row, column, or table context.",
    )
    exclude_phrases: list[str] = Field(
        default_factory=list,
        description="Close-but-wrong phrases to reject if present.",
    )
    prefer_total_row: bool = False
    requires_component_sum: bool = Field(
        default=False,
        description="True only when the answer must sum multiple component rows/cells, not when row_phrases are synonyms.",
    )
    target_unit: Unit = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("row_phrases", "context_phrases", "include_phrases", "exclude_phrases", mode="before")
    @classmethod
    def _phrases(cls, value):
        seen: set[str] = set()
        out: list[str] = []
        for raw in value or []:
            phrase = str(raw).strip()
            norm = _norm(phrase)
            if not phrase or not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(phrase[:120])
        return out[:8]


class RawTableLinkError(Exception):
    """Unsupported or ambiguous raw-table linking plan."""


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


def _scope_identity_tokens(slots: Sequence[RawScopeSlot], doc_type: str) -> list[str]:
    tokens: set[str] = set()
    for slot in slots:
        tokens.update(_tokens(slot.ticker))
        for table_id in _scope_table_ids(slot, doc_type):
            company_name = meta_for(table_id).get("company_name")
            if company_name:
                tokens.update(_tokens(company_name))
                break
    return sorted(tokens)


def build_request(state: Mapping[str, Any]) -> tuple[RawLinkRequest | None, str]:
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
    identity_tokens = _scope_identity_tokens(slots, doc_type)
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


def should_attempt_raw_table_linker(state: Mapping[str, Any]) -> tuple[bool, str]:
    request, reason = build_request(state)
    return (request is not None), reason


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


def _scope_ok(table_id: str, slot: RawScopeSlot, doc_type: str) -> bool:
    meta = meta_for(table_id)
    if str(meta.get("ticker") or "").upper() != slot.ticker:
        return False
    if str(meta.get("year") or "") != str(slot.year):
        return False
    if doc_type in {"consolidated", "separate"} and str(meta.get("doc_type") or "") != doc_type:
        return False
    return True


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


def _scope_table_ids(slot: RawScopeSlot, doc_type: str) -> list[str]:
    out: list[str] = []
    for table_id, meta in table_metadata().items():
        if str(meta.get("ticker") or "").upper() != slot.ticker:
            continue
        if str(meta.get("year") or "") != str(slot.year):
            continue
        if doc_type in {"consolidated", "separate"} and str(meta.get("doc_type") or "") != doc_type:
            continue
        out.append(table_id)
    return out


def _candidate_rows(
    request: RawLinkRequest,
    slot: RawScopeSlot,
    table_id: str,
    ranked: Sequence[str],
    *,
    start_id: int,
) -> list[RawCellCandidate]:
    try:
        df = load_frame(table_id)
    except Exception:  # noqa: BLE001 - one unreadable table cannot answer
        return []
    if df.empty or df.shape[1] < 2:
        return []

    meta = meta_for(table_id)
    profile_label_col = None
    try:
        profile = build_table_profile(table_id, df)
        profile_labels = [row.label for row in profile.rows]
        profile_label_col = next((col for col in profile.label_columns if col in df.columns), None)
    except Exception:  # noqa: BLE001 - profile is advisory for linking
        profile_labels = []
    context = _table_context(meta, profile_labels)
    scoring_tokens, scoring_norm = _scoring_query_for_table(request, table_id)
    table_score = _semantic_score(scoring_tokens, scoring_norm, context)
    label_col = profile_label_col or label_column(df)
    table_year = int(meta["year"]) if str(meta.get("year") or "").isdigit() else None
    # Section ancestors carry the metric on note tables whose value rows are
    # labelled by period only; identifier columns (`Mã số`, `Thuyết minh`) are
    # numeric but are not values.
    row_paths = {
        position: profile.path
        for position, profile in build_row_profiles(table_id, df=df, label_col=label_col).items()
        if profile.path and not profile.is_section_header
    }
    try:
        column_profiles = {
            profile.name: profile for profile in build_column_profiles(table_id, df=df)
        }
    except Exception:  # noqa: BLE001 - header enrichment is advisory for linking
        column_profiles = {}
    # Column scores do not depend on the row, so they are computed once per table.
    column_scores: dict[object, float] = {}
    for column in df.columns:
        if column == label_col:
            continue
        profile = column_profiles.get(str(column))
        if profile is not None and profile.is_identifier:
            continue
        # A share-of-total column cannot answer a question asked in đồng, and it holds a
        # number in the same row as the amount, so it wins ties it has no claim to.
        if request.target_unit in _MONEY_UNITS and _is_percent_column(column):
            continue
        column_scores[column] = max(0.0, min(1.0, _column_score(
            column,
            slot_year=slot.year,
            period=request.period,
            table_year=table_year,
            resolved_year=profile.resolved_year if profile else None,
        ) + _flow_column_adjustment(request, column)))

    # A breakdown table (`Điện | Than | Khác | Cộng`) holds the answer in its total
    # column unless the question names one of the parts. `_column_score` reads only
    # period wording, so those four columns tied and row order picked the winner.
    total_columns = {c for c in column_scores if _is_total_row(_norm(_leaf(c)))}
    if total_columns and not any(
        _token_score(scoring_tokens, _leaf(c)) > 0 for c in column_scores if c not in total_columns
    ):
        for column in total_columns:
            column_scores[column] = min(1.0, column_scores[column] + 0.12)

    # `Cộng` says nothing about what is being added, so a total row borrows the best
    # score among the rows above it. This used to run only when the question spelled out
    # "tổng", which left every other total row at exactly 0 on the row axis: q109 asks
    # for prepayments to sellers and the answer is the note's `Cộng` row, scored 0.00.
    row_anchor = 0.0
    for position, raw_label in df[label_col].items():
        label = _text(raw_label)
        if label and not _is_total_row(label):
            row_anchor = max(
                row_anchor,
                _semantic_score(
                    scoring_tokens, scoring_norm, _row_text(label, row_paths.get(position))
                ),
            )
    out: list[RawCellCandidate] = []

    for position, row in df.iterrows():
        row_label = _text(row.get(label_col))
        synthetic_total = False
        if not row_label and request.operation == "ratio" and _row_has_numeric_value(row, label_col):
            row_label = "Cộng"
            synthetic_total = True
        if not row_label:
            continue
        row_path = list(row_paths.get(position) or []) if _labels_a_row(row_label) else []
        total_row = _is_total_row(row_label)
        if synthetic_total:
            total_row = True
        generic_period_row = _is_generic_period_row(row_label)
        if not total_row and generic_period_row and request.operation != "ratio" and not row_path:
            # Without ancestors such a row has no linkable wording at all.
            continue
        row_score = (
            row_anchor if total_row
            else _semantic_score(scoring_tokens, scoring_norm, _row_text(row_label, row_path))
        )
        if request.operation == "ratio" and generic_period_row:
            row_score = max(row_score, _generic_period_row_score(row_label, request.period))
        if not total_row:
            row_score = max(
                0.0,
                min(1.0, row_score + _row_period_adjustment(row_label, request.period)),
            )
        for column in df.columns:
            if column == label_col:
                continue
            if column not in column_scores:
                continue
            value = _safe_number(row[column])
            if value is None:
                continue
            col_score = column_scores[column]
            component_role = _component_role_from_text(
                _norm(f"{_row_text(row_label, row_path)} {column}"),
                is_total=total_row,
            )
            total_adjust = 0.0
            if request.wants_total:
                if total_row:
                    total_adjust = 0.35
                elif request.operation == "ratio" and component_role in _ratio_numerator_roles(request):
                    total_adjust = 0.0
                else:
                    total_adjust = -0.18
            elif total_row:
                # It borrowed the best row's score, so without it a total row would tie
                # the specific row it borrowed from. Enough to lose that tie, not enough
                # to fall behind rows the question does not name at all.
                total_adjust = -0.06
            elif _is_component_row(row_label) and row_score < row_anchor:
                # The dash is a printing convention, so charge it only while some other
                # row answers the question better. q313 asks for `Chi phí công cụ, dụng
                # cụ chờ phân bổ` and the note prints exactly that, under a dash.
                total_adjust = -0.12
            source_unit, source_unit_from = detect_unit(df, str(column), page_text(table_id))
            score = (
                row_score * 0.42
                + table_score * 0.24
                + col_score * 0.24
                + total_adjust
                + _rank_bonus(table_id, ranked)
            )
            if row_score == 0 and table_score < 0.18 and not (request.wants_total and total_row):
                continue
            if col_score <= 0 and request.period != "unknown":
                continue
            if score < 0.18:
                continue
            out.append(
                RawCellCandidate(
                    id=f"c{start_id + len(out)}",
                    slot_key=slot.key,
                    table_id=table_id,
                    ticker=slot.ticker,
                    year=slot.year,
                    row_position=int(position),
                    row_label=row_label,
                    row_path=row_path,
                    column=str(column),
                    value=float(value),
                    source_unit=(source_unit or "unknown"),  # type: ignore[arg-type]
                    source_unit_from=source_unit_from,
                    is_total_row=total_row,
                    row_score=round(row_score, 3),
                    table_score=round(table_score, 3),
                    column_score=round(col_score, 3),
                    score=round(max(0.0, min(score, 1.0)), 3),
                    table_context=_short_context(context, 420),
                )
            )
    return out


def build_candidates(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    limit_per_slot: int = 12,
    max_tables: int = 140,
) -> tuple[list[RawCellCandidate], dict[str, Any]]:
    """Build bounded candidates for each scope slot from raw CSV tables."""
    ranked = list(dict.fromkeys([*table_ids, *shortlist]))
    all_candidates: list[RawCellCandidate] = []
    per_slot: dict[str, int] = {}
    per_slot_scanned: dict[str, int] = {}
    missing: list[str] = []
    next_id = 1
    for slot in request.slots:
        slot_candidates: list[RawCellCandidate] = []
        slot_ranked = list(dict.fromkeys([
            *[table_id for table_id in ranked if _scope_ok(table_id, slot, request.doc_type)],
            *_scope_table_ids(slot, request.doc_type),
        ]))[:max_tables]
        per_slot_scanned[slot.key] = len(slot_ranked)
        for table_id in slot_ranked:
            if not _scope_ok(table_id, slot, request.doc_type):
                continue
            rows = _candidate_rows(request, slot, table_id, ranked, start_id=next_id)
            next_id += len(rows)
            slot_candidates.extend(rows)
        slot_candidates.sort(
            key=lambda c: (
                -c.score,
                -c.row_score,
                -c.table_score,
                -c.column_score,
                c.table_id,
                c.row_position,
            )
        )
        kept = slot_candidates[:limit_per_slot]
        if not kept:
            missing.append(slot.key)
        per_slot[slot.key] = len(kept)
        all_candidates.extend(kept)
    # Reassign compact ids after per-slot pruning; this keeps planner prompts short.
    compact: list[RawCellCandidate] = []
    for index, candidate in enumerate(all_candidates, 1):
        compact.append(candidate.model_copy(update={"id": f"c{index}"}))
    return compact, {
        "candidate_count": len(compact),
        "per_slot": per_slot,
        "per_slot_scanned": per_slot_scanned,
        "missing_slots": missing,
    }


def _group_role_score(request: RawLinkRequest, group: RawGroupCandidate) -> float:
    norm = request.query_norm
    if group.semantic_role == "lt_1y" and re.search(r"\b(?:ngan\s+han|duoi\s+(?:1|mot)\s+nam|duoi\s+12\s+thang)\b", norm):
        return 0.28
    if group.semantic_role == "total" and re.search(r"\b(?:tong|tong\s+du\s+no|trong\s+tong|tren\s+tong)\b", norm):
        return 0.22
    if group.semantic_role in {"1_to_5y", "gt_5y"} and group.semantic_role in norm:
        return 0.16
    return 0.0


def _score_group_candidate(
    request: RawLinkRequest,
    group: RawGroupCandidate,
    *,
    table_score: float,
    rank_bonus: float,
) -> RawGroupCandidate:
    row_label = group.label.split("::", 1)[0]
    scoring_tokens = request.query_tokens
    row_score = _semantic_score(scoring_tokens, request.query_norm, row_label)
    score = row_score * 0.46 + table_score * 0.24 + _group_role_score(request, group) + rank_bonus
    return group.model_copy(update={"score": round(max(0.0, min(score, 1.0)), 3)})


def build_ratio_candidates(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    cell_limit_per_slot: int = 32,
    group_limit_per_slot: int = 18,
    max_tables: int = 140,
) -> tuple[list[RawLinkedCandidate], dict[str, Any]]:
    """Build cell and group candidates for component-ratio planning."""
    cells, cell_diag = build_candidates(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        limit_per_slot=cell_limit_per_slot,
        max_tables=max_tables,
    )
    ranked = list(dict.fromkeys([*table_ids, *shortlist]))
    groups_by_slot: dict[str, int] = {}
    all_groups: list[RawGroupCandidate] = []
    next_id = 1
    for slot in request.slots:
        slot_groups: list[RawGroupCandidate] = []
        slot_ranked = [
            table_id for table_id in ranked
            if _scope_ok(table_id, slot, request.doc_type)
        ][:max_tables]
        for table_id in slot_ranked:
            if not _scope_ok(table_id, slot, request.doc_type):
                continue
            try:
                df = load_frame(table_id)
                profile = build_table_profile(table_id, df)
                context = _table_context(meta_for(table_id), [row.label for row in profile.rows])
                scoring_tokens, scoring_norm = _scoring_query_for_table(request, table_id)
                table_score = _semantic_score(scoring_tokens, scoring_norm, context)
                raw_groups = build_column_group_candidates(
                    table_id,
                    slot,
                    df=df,
                    start_id=next_id,
                )
            except Exception:  # noqa: BLE001 - advisory group extraction must fail closed
                continue
            next_id += len(raw_groups)
            for group in raw_groups:
                scored = _score_group_candidate(
                    request,
                    group,
                    table_score=table_score,
                    rank_bonus=_rank_bonus(table_id, ranked),
                )
                if scored.score >= 0.18:
                    slot_groups.append(scored)
        slot_groups.sort(
            key=lambda group: (
                -group.score,
                group.table_ids[0] if group.table_ids else "",
                group.label,
                group.semantic_role,
            )
        )
        kept = slot_groups[:group_limit_per_slot]
        groups_by_slot[slot.key] = len(kept)
        all_groups.extend(kept)

    compact_groups: list[RawGroupCandidate] = []
    for index, group in enumerate(all_groups, 1):
        compact_groups.append(group.model_copy(update={"id": f"g{index}"}))
    candidates: list[RawLinkedCandidate] = [*cells, *compact_groups]
    diag = dict(cell_diag)
    diag.update({
        "candidate_count": len(candidates),
        "cell_candidate_count": len(cells),
        "group_candidate_count": len(compact_groups),
        "groups_per_slot": groups_by_slot,
    })
    return candidates, diag


def _ratio_numerator_roles(request: RawLinkRequest) -> set[str]:
    norm = request.query_norm
    if re.search(r"\b(?:ngan\s+han|duoi\s+(?:1|mot)\s+nam|duoi\s+12\s+thang)\b", norm):
        return {"lt_1y"}
    if re.search(r"\b(?:trung\s+han|1\s+(?:toi|den)\s+5\s+nam|tu\s+tren\s+1\s+nam\s+den\s+5\s+nam)\b", norm):
        return {"1_to_5y"}
    if re.search(r"\b(?:dai\s+han|tren\s+5\s+nam)\b", norm):
        return {"gt_5y"}
    return {"lt_1y", "1_to_5y", "gt_5y"}


def _ratio_side_for_candidate(request: RawLinkRequest, candidate: RawLinkedCandidate) -> set[str]:
    role = _candidate_component_role(candidate)
    out: set[str] = set()
    if role in _ratio_numerator_roles(request):
        out.add("numerator")
    if role == "total" or _is_total_candidate(candidate):
        out.add("denominator")
    if isinstance(candidate, RawCellCandidate):
        text = _norm(f"{candidate.row_path_text} {candidate.column}")
        numerator_roles = _ratio_numerator_roles(request)
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
        if _CURRENT_COL.search(text):
            return 1
        if _PRIOR_COL.search(text):
            return -1
    if request.period == "prior":
        if _PRIOR_COL.search(text):
            return 1
        if _CURRENT_COL.search(text):
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
        if side == "numerator" and role in _ratio_numerator_roles(request):
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
                    ",".join(_candidate_table_ids(candidate)),
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
                        table_ids=_candidate_table_ids(candidate),
                        context=_short_context(_candidate_context(candidate), 220),
                        score=candidate.score,
                    )
                )
    return options, {
        "option_count": len(options),
        "per_slot_side": counts,
        "missing_options": missing,
    }


def render_ratio_options(
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
) -> str:
    lines = [
        f"Operation inferred: {request.operation}",
        f"Ratio aggregate: {'average of per-slot ratios' if request.ratio_aggregate == 'avg' else 'single ratio'}",
        "Choose exactly one numerator option and one denominator option for each slot.",
    ]
    by_slot: dict[str, dict[str, list[RawRatioOption]]] = {
        slot.key: {"numerator": [], "denominator": []}
        for slot in request.slots
    }
    for option in options:
        if option.slot_key in by_slot:
            by_slot[option.slot_key][option.side].append(option)
    for slot in request.slots:
        lines.append(f"Slot {slot.key}:")
        for side, title in (("numerator", "Numerator options"), ("denominator", "Denominator options")):
            lines.append(f"  {title}:")
            for option in by_slot[slot.key][side]:
                lines.append(
                    f"  - {option.id} kind={option.source_kind} "
                    f"label={option.label!r} role={option.semantic_role or '?'} "
                    f"tables={option.table_ids} "
                    f"value={_format_value(option.value)} unit={option.unit} "
                    f"candidate_ids={option.candidate_ids} score={option.score:.2f} "
                    f"context={option.context!r}"
                )
    return "\n".join(lines)


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
        numerator_roles = _ratio_numerator_roles(request)
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
    return request.ratio_aggregate == "avg" and _ratio_numerator_roles(request) != all_maturity_roles


def _candidate_table_ids(candidate: RawLinkedCandidate) -> list[str]:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.table_ids
    return [candidate.table_id]


def _candidate_query(
    candidate: RawLinkedCandidate,
    table_to_var: Mapping[str, str],
    transform: str,
) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.query(table_to_var, transform)  # type: ignore[arg-type]
    return candidate.query(table_to_var[candidate.table_id], transform)  # type: ignore[arg-type]


def _candidate_first_cell(candidate: RawLinkedCandidate) -> tuple[str, int, str, str]:
    if isinstance(candidate, RawGroupCandidate):
        first = candidate.cells[0]
        return first.table_id, first.row_position, first.column, first.source_unit
    return candidate.table_id, candidate.row_position, candidate.column, candidate.source_unit


def render_candidates(request: RawLinkRequest, candidates: Sequence[RawLinkedCandidate]) -> str:
    lines = [
        f"Operation inferred: {request.operation}",
        "Required slots in order: " + ", ".join(slot.key for slot in request.slots),
        "Candidates:",
    ]
    for candidate in candidates:
        if isinstance(candidate, RawGroupCandidate):
            flags = []
            if candidate.semantic_role:
                flags.append(f"role={candidate.semantic_role}")
            if candidate.table_context:
                flags.append(f"context={candidate.table_context[:420]}")
            cell_refs = ", ".join(
                f"{cell.table_id}:r{cell.row_position}:{cell.column}"
                for cell in candidate.cells[:8]
            )
            lines.append(
                f"- {candidate.id} kind=group slot={candidate.slot_key} "
                f"tables={candidate.table_ids} label={candidate.label!r} "
                f"op={candidate.group_op} cells=[{cell_refs}] "
                f"value={_format_value(candidate.value)} unit={candidate.source_unit} "
                f"signals=(score={candidate.score:.2f}) "
                + (" ".join(flags) if flags else "")
            )
            continue
        flags = []
        if candidate.row_path:
            flags.append(f"row_path={' > '.join(candidate.row_path)!r}")
        if candidate.is_total_row:
            flags.append("total_row")
        if candidate.table_context:
            flags.append(f"context={candidate.table_context[:420]}")
        if candidate.source_unit_from:
            flags.append(f"unit_from={candidate.source_unit_from[:120]}")
        signal = (
            f"score={candidate.score:.2f}; row={candidate.row_score:.2f}; "
            f"table={candidate.table_score:.2f}; column={candidate.column_score:.2f}"
        )
        lines.append(
            f"- {candidate.id} slot={candidate.slot_key} table={candidate.table_id} "
            f"row={candidate.row_position} label={candidate.row_label!r} "
            f"column={candidate.column!r} value={_format_value(candidate.value)} "
            f"unit={candidate.source_unit} signals=({signal}) "
            + (" ".join(flags) if flags else "")
        )
    return "\n".join(lines)


def _dedupe_texts(values: Sequence[object], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        norm = _norm(text)
        if not text or not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _table_label_snippets(
    request: RawLinkRequest,
    table_id: str,
    df: pd.DataFrame,
    profile_labels: Sequence[str],
    *,
    limit: int,
) -> list[str]:
    meta = meta_for(table_id)
    labels: list[object] = []
    labels.extend(_text_list(meta.get("first_col_labels")))
    labels.extend(profile_labels)
    try:
        label_col = label_column(df)
        labels.extend(df[label_col].tolist())
    except Exception:  # noqa: BLE001 - labels are advisory evidence for the planner
        pass

    initial = _dedupe_texts(labels, limit=4)
    scoring_tokens, scoring_norm = _scoring_query_for_table(request, table_id)
    ranked = sorted(
        _dedupe_texts(labels, limit=80),
        key=lambda label: _semantic_score(scoring_tokens, scoring_norm, label),
        reverse=True,
    )
    return _dedupe_texts([*initial, *ranked], limit=limit)


def render_table_contexts(
    request: RawLinkRequest,
    *,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    limit_per_slot: int = 24,
    labels_per_table: int = 8,
    max_tables: int = 140,
) -> str:
    """Render real table snippets so the LLM maps question wording to table wording."""
    ranked = list(dict.fromkeys([*table_ids, *shortlist]))
    lines = [
        "Real table snippets in scope. Copy phrase wording from these snippets when possible.",
    ]
    for slot in request.slots:
        slot_ranked = list(dict.fromkeys([
            *[table_id for table_id in ranked if _scope_ok(table_id, slot, request.doc_type)],
            *_scope_table_ids(slot, request.doc_type),
        ]))[:max_tables]
        scored_tables: list[tuple[float, float, float, str, Mapping[str, Any], list[str], str]] = []
        for table_id in slot_ranked:
            try:
                df = load_frame(table_id)
            except Exception:  # noqa: BLE001 - one unreadable table should not block evidence
                continue
            if df.empty:
                continue
            meta = meta_for(table_id)
            try:
                profile = build_table_profile(table_id, df)
                profile_labels = [row.label for row in profile.rows]
            except Exception:  # noqa: BLE001 - profile is advisory
                profile_labels = []
            context = _table_context(meta, profile_labels)
            scoring_tokens, scoring_norm = _scoring_query_for_table(request, table_id)
            context_score = _semantic_score(scoring_tokens, scoring_norm, context)
            labels = _table_label_snippets(
                request, table_id, df, profile_labels, limit=labels_per_table,
            )
            row_score = max(
                (_semantic_score(scoring_tokens, scoring_norm, label) for label in labels),
                default=0.0,
            )
            rank_bonus = _rank_bonus(table_id, ranked)
            score = context_score * 0.62 + row_score * 0.28 + rank_bonus
            if score <= 0:
                continue
            scored_tables.append((score, context_score, row_score, table_id, meta, labels, context))
        scored_tables.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        lines.append(f"Slot {slot.key}:")
        for score, context_score, row_score, table_id, meta, labels, context in scored_tables[:limit_per_slot]:
            title = _text(meta.get("note_title")) or _text(meta.get("section_title")) or _text(meta.get("statement_type"))
            header = _text(meta.get("header_flat"))
            page_hint = _short_context(_text(meta.get("context_page_text")), 260)
            if page_hint and page_hint in context:
                page_hint = _short_context(page_hint, 180)
            line = (
                f"- table={table_id}; title={title!r}; header={header!r}; "
                f"signals=({score:.2f}, context={context_score:.2f}, rows={row_score:.2f}); "
                f"labels={labels}"
            )
            if page_hint:
                line += f"; page_hint={page_hint!r}"
            lines.append(line)
    return "\n".join(lines)


RAW_LINKER_SYSTEM = """\
Bạn chọn ô từ raw financial table candidates để executor Python tính toán.
Chỉ trả schema RawLinkerDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi candidate là một ô thật trong CSV.
- Chọn đúng một candidate cho mỗi required slot.
- Với operation=diff, thứ tự candidate_ids phải theo Required slots: slot 1 trừ slot 2.
- Với avg/sum, chọn đủ các slot được yêu cầu.
- Ưu tiên dòng tổng/Cộng khi câu hỏi hỏi tổng số dư/tổng giá trị.
- Nếu chọn được đủ candidate_ids tốt nhất cho các required slots thì supported=true.
- Dùng unsupported chỉ khi thiếu slot, thiếu ô đúng, đơn vị không cùng loại, hoặc candidates mơ hồ.
"""


RAW_RATIO_LINKER_SYSTEM = """\
Bạn chọn các ô numerator/denominator từ raw financial table candidates.
Chỉ trả schema RawRatioDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi candidate là một ô thật trong CSV.
- Mỗi slot_key phải có numerator_candidate_ids và denominator_candidate_ids.
- Một phía có thể gồm nhiều candidate_ids nếu câu hỏi cần cộng nhiều component.
- Nếu có sẵn dòng/cột tổng đúng semantic thì ưu tiên dùng tổng thay vì cộng component.
- Không bao giờ chọn đồng thời một dòng/cột tổng và các component đã tạo ra tổng đó trong cùng một phía.
- Không chọn dòng phát sinh trong năm/trả trong năm nếu câu hỏi hỏi số dư cuối năm.
- Với câu hỏi phần trăm, vẫn chọn raw money cells; executor sẽ nhân 100 sau khi chia.
- Nếu candidates không đủ để biểu diễn đầy đủ numerator/denominator cho mọi slot thì supported=false.
"""


RAW_RATIO_OPTION_SYSTEM = """\
Bạn chọn option numerator/denominator cho ratio tài chính.
Chỉ trả schema RawRatioOptionDecision. Không viết pandas, không tự tính số.

Quy tắc:
- Mỗi slot_key phải chọn đúng một numerator_option_id và một denominator_option_id.
- Chỉ chọn option nằm trong đúng slot và đúng side.
- Numerator là phần được hỏi: ví dụ nợ ngắn hạn, dưới 1 năm, tài sản vô hình.
- Denominator là tổng/nền mẫu: ví dụ tổng dư nợ, tổng tài sản, tổng tài sản cố định.
- Nếu trong cùng slot có kind=cell với row label trực tiếp đúng phần được hỏi, ưu tiên nó hơn kind=group suy diễn từ nhiều cột.
- Nếu thiếu option đúng cho bất kỳ slot nào thì supported=false.
"""


async def aplan_raw_table_linker(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
) -> RawLinkerDecision:
    user = f"Câu hỏi: {question}\n\n{render_candidates(request, candidates)}"
    try:
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            RawLinkerDecision,
            method=STRUCTURED_METHOD,
        ).ainvoke([SystemMessage(content=RAW_LINKER_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason=f"planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawLinkerDecision(
            supported=False,
            operation=request.operation,
            reason="planner returned no structured decision",
        )
    return result if isinstance(result, RawLinkerDecision) else RawLinkerDecision.model_validate(result)


async def aplan_raw_ratio_options(
    *,
    question: str,
    request: RawLinkRequest,
    options: Sequence[RawRatioOption],
    planner_thinking: bool = False,
) -> RawRatioOptionDecision:
    user = f"Câu hỏi: {question}\n\n{render_ratio_options(request, options)}"
    try:
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            RawRatioOptionDecision,
            method=STRUCTURED_METHOD,
        ).ainvoke([SystemMessage(content=RAW_RATIO_OPTION_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawRatioOptionDecision(
            supported=False,
            operation="ratio",
            reason=f"ratio option planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawRatioOptionDecision(
            supported=False,
            operation="ratio",
            reason="ratio option planner returned no structured decision",
        )
    return result if isinstance(result, RawRatioOptionDecision) else RawRatioOptionDecision.model_validate(result)


async def aplan_raw_ratio_linker(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
) -> RawRatioDecision:
    aggregate = "average of per-slot ratios" if request.ratio_aggregate == "avg" else "single ratio per slot"
    user = (
        f"Câu hỏi: {question}\n"
        f"Ratio aggregate: {aggregate}\n\n"
        f"{render_candidates(request, candidates)}"
    )
    try:
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=1024,
            temperature=0.0,
        ).with_structured_output(
            RawRatioDecision,
            method=STRUCTURED_METHOD,
        ).ainvoke([SystemMessage(content=RAW_RATIO_LINKER_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawRatioDecision(
            supported=False,
            operation="ratio",
            reason=f"ratio planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawRatioDecision(supported=False, operation="ratio", reason="ratio planner returned no structured decision")
    return result if isinstance(result, RawRatioDecision) else RawRatioDecision.model_validate(result)



RAW_SEMANTIC_SYSTEM = """\
Bạn tạo semantic constraints để chọn ô trong raw financial table candidates.
Chỉ trả schema RawSemanticPlan. Không chọn candidate_id, không viết pandas, không tự tính số.

Mỗi required slot cần một RawSlotSemanticConstraint cùng slot_key.
row_phrases là cụm phân biệt phải nằm ở row label của ô đúng.
context_phrases là cụm phân biệt table/note, như tiêu đề thuyết minh.
include_phrases chỉ dùng khi cụm có thể nằm ở row, column hoặc context.
Có thể dùng cụm tương đương xuất hiện trong candidates, không nhất thiết y
nguyên câu hỏi. Không đưa tên công ty, năm, đơn vị, hoặc từ tính toán vào các
phrase fields.
exclude_phrases dùng cho các khái niệm gần nhưng sai nếu candidates có chúng.
Nếu candidates không đủ để phân biệt ô đúng, supported=false.
"""


RAW_SEARCH_SYSTEM = """\
Bạn chuyển câu hỏi tài chính thành cụm tìm kiếm để tìm row trong raw tables.
Chỉ trả schema RawSearchPlan. Không chọn candidate_id, không viết pandas,
không tự tính số.

row_phrases: cụm có khả năng xuất hiện ở row label hoặc fragment phân biệt
trong row label của ô đúng. Ưu tiên copy đúng wording từ real table snippets.
context_phrases: cụm nhận diện note/table nếu cần.
include_phrases: cụm có thể nằm ở row, column hoặc context.
exclude_phrases: cụm gần nghĩa nhưng sai cần loại.
requires_component_sum=true chỉ khi đáp án phải cộng nhiều dòng/cell component
trong cùng slot; false nếu row_phrases chỉ là các cách gọi/synonym của cùng một
metric.
Các snippets chỉ hiển thị labels/context, không hiển thị numeric values; không
được unsupported chỉ vì chưa thấy giá trị số.
Phrase fields sẽ áp cho mọi required slot, nên không đưa tên công ty, ticker,
năm, đơn vị, mã form, hoặc từ tính toán vào phrase fields.
Nếu snippets không cho đủ bằng chứng semantic về row/context, supported=false.
"""


async def aplan_raw_search(
    *,
    question: str,
    request: RawLinkRequest,
    table_ids: Sequence[str] = (),
    shortlist: Sequence[str] = (),
    planner_thinking: bool = False,
) -> RawSearchPlan:
    slots = ", ".join(slot.key for slot in request.slots)
    table_context_limit = 24 if len(request.slots) <= 2 else 12
    table_contexts = render_table_contexts(
        request,
        table_ids=table_ids,
        shortlist=shortlist,
        limit_per_slot=table_context_limit,
    )
    user = (
        f"Câu hỏi: {question}\n"
        f"Operation: {request.operation}\n"
        f"Required slots: {slots}\n"
        f"Question tokens without identity: "
        f"{' '.join(token for token in request.query_tokens if token not in set(request.identity_tokens))}\n\n"
        f"{table_contexts}"
    )
    try:
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=512,
            temperature=0.0,
        ).with_structured_output(
            RawSearchPlan,
            method=STRUCTURED_METHOD,
        ).ainvoke([SystemMessage(content=RAW_SEARCH_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawSearchPlan(
            supported=False,
            reason=f"search planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawSearchPlan(supported=False, reason="search planner returned no structured plan")
    return result if isinstance(result, RawSearchPlan) else RawSearchPlan.model_validate(result)


def request_with_search_plan(request: RawLinkRequest, plan: RawSearchPlan | None) -> RawLinkRequest:
    if plan is None or not plan.supported:
        return request
    expansion = " ".join([
        *plan.row_phrases,
        *plan.context_phrases,
        *plan.include_phrases,
    ])
    if not expansion.strip():
        return request
    expanded_text = f"{request.query_norm} {_norm(expansion)}"
    return request.model_copy(update={
        "query_norm": _norm(expanded_text),
        "query_tokens": _tokens(expanded_text),
        "target_unit": plan.target_unit if plan.target_unit != "unknown" else request.target_unit,
        "wants_total": request.wants_total or plan.prefer_total_row,
    })


def semantic_plan_from_search_plan(request: RawLinkRequest, plan: RawSearchPlan) -> RawSemanticPlan:
    if not plan.supported:
        return RawSemanticPlan(
            supported=False,
            operation=request.operation,
            target_unit=request.target_unit,
            reason=plan.reason or "search planner marked unsupported",
        )
    return RawSemanticPlan(
        supported=True,
        operation=request.operation,
        target_unit=plan.target_unit if plan.target_unit != "unknown" else request.target_unit,
        confidence=plan.confidence,
        reason=plan.reason,
        slots=[
            RawSlotSemanticConstraint(
                slot_key=slot.key,
                row_phrases=plan.row_phrases,
                context_phrases=plan.context_phrases,
                include_phrases=plan.include_phrases,
                exclude_phrases=plan.exclude_phrases,
                prefer_total_row=plan.prefer_total_row,
                requires_component_sum=plan.requires_component_sum,
            )
            for slot in request.slots
        ],
    )


async def aplan_raw_semantics(
    *,
    question: str,
    request: RawLinkRequest,
    candidates: Sequence[RawCellCandidate],
    planner_thinking: bool = False,
) -> RawSemanticPlan:
    user = f"Câu hỏi: {question}\n\n{render_candidates(request, candidates)}"
    try:
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=768,
            temperature=0.0,
        ).with_structured_output(
            RawSemanticPlan,
            method=STRUCTURED_METHOD,
        ).ainvoke([SystemMessage(content=RAW_SEMANTIC_SYSTEM), HumanMessage(content=user)])
    except Exception as exc:  # noqa: BLE001 - fallback is product behavior
        return RawSemanticPlan(
            supported=False,
            operation=request.operation,
            reason=f"semantic planner unavailable: {type(exc).__name__}: {exc}",
        )
    if result is None:
        return RawSemanticPlan(
            supported=False,
            operation=request.operation,
            reason="semantic planner returned no structured plan",
        )
    return result if isinstance(result, RawSemanticPlan) else RawSemanticPlan.model_validate(result)


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
    # only borrows the wording from the section header above it: `Thuế suất thuế
    # TNDN > Chi phí thuế TNDN hiện hành ước tính` would otherwise tie with the
    # real `Chi phí thuế thu nhập doanh nghiệp hiện hành` row.
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
    # Exclusion names close-but-wrong candidates, so it is scoped to the cell's
    # own row/column wording. Matching it against page-wide context would reject
    # the right row of a note whose sibling rows are the wrong ones.
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


def _unit_kind(unit: str) -> str:
    if unit in MONEY_SCALE or unit == "unknown":
        return "money"
    return unit


def _effective_target_unit(request: RawLinkRequest, decision: RawLinkerDecision) -> str:
    return decision.target_unit if decision.target_unit != "unknown" else request.target_unit


def _validate_operation_unit_compatibility(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
    chosen: Sequence[RawCellCandidate],
) -> None:
    target = _effective_target_unit(request, decision)
    kinds = {_unit_kind(candidate.source_unit) for candidate in chosen}
    if len(kinds) > 1:
        raise RawTableLinkError(f"mixed unit kinds: {sorted(kinds)}")
    if not kinds:
        return
    source_kind = next(iter(kinds))
    if target in {"ratio", "percent"} and source_kind == "money" and request.operation != "ratio":
        raise RawTableLinkError("ratio/percent target cannot be answered by money-cell arithmetic")
    if target in MONEY_SCALE and source_kind in {"ratio", "percent"}:
        raise RawTableLinkError("money target cannot be answered by ratio/percent cells")


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
    return len({_unit_kind(candidate.source_unit) for candidate in candidates}) <= 1


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
    """Choose top-ranked cells when the score pattern is strong enough.

    This is deliberately conservative: it only handles fixed-scope arithmetic
    where every required slot has a high-signal top candidate. Ambiguous cases
    still go to the LLM planner and then to codegen fallback.
    """
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


def _label_family(label: str) -> str:
    without_parenthetical = re.sub(r"\([^)]*\)", " ", label)
    norm = _norm(without_parenthetical)
    norm = re.sub(r"^(?:\d+|[ivxlcdm]+)\s+", "", norm).strip()
    return norm


def _is_total_candidate(candidate: RawLinkedCandidate) -> bool:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.semantic_role == "total"
    return candidate.is_total_row


def _candidate_family_label(candidate: RawLinkedCandidate) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.label.split("::", 1)[0]
    return candidate.row_path_text


def _candidate_component_role(candidate: RawLinkedCandidate) -> str:
    if isinstance(candidate, RawGroupCandidate):
        return candidate.semantic_role
    return _component_role_from_text(
        _norm(f"{candidate.row_path_text} {candidate.column}"),
        is_total=candidate.is_total_row,
    )


def _component_group_family(candidates: Sequence[RawLinkedCandidate]) -> str:
    if candidates and all(_is_total_candidate(candidate) for candidate in candidates):
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
        if (role := _candidate_component_role(candidate))
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

        kinds = {_unit_kind(candidate.source_unit) for candidate in [*numerator, *denominator]}
        if len(kinds) > 1:
            raise RawTableLinkError(f"ratio candidates have mixed unit kinds: {sorted(kinds)}")
        if len(numerator) > 1 and any(_is_total_candidate(candidate) for candidate in numerator):
            raise RawTableLinkError(f"ratio numerator mixes a total row with components for {slot_decision.slot_key}")
        if len(denominator) > 1 and any(_is_total_candidate(candidate) for candidate in denominator):
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

    expected = _expected_candidate_count(request)
    if len(chosen) != expected:
        raise RawTableLinkError(f"needs {expected} candidates, got {len(chosen)}")

    slot_order = [slot.key for slot in request.slots]
    chosen_slots = [candidate.slot_key for candidate in chosen]
    if request.operation in {"diff", "sum", "avg"} and chosen_slots != slot_order:
        raise RawTableLinkError(f"candidate order/scope mismatch: {chosen_slots} != {slot_order}")
    if any(candidate.score < min_candidate_score for candidate in chosen):
        raise RawTableLinkError("selected candidate score below threshold")
    if request.operation == "direct" and any(candidate.score < _MIN_DIRECT_SCORE for candidate in chosen):
        raise RawTableLinkError("direct candidate evidence below threshold")
    if any(candidate.value == 0.0 for candidate in chosen):
        raise RawTableLinkError("selected candidate value is zero")
    if _normalized_from_unsupported(decision) and request.operation in {"diff", "sum", "avg"}:
        coherent = _same_row_labels(chosen) or (
            request.wants_total and all(candidate.is_total_row for candidate in chosen)
        )
        if not coherent:
            raise RawTableLinkError("unsupported planner ids need coherent row evidence")

    _validate_operation_unit_compatibility(request, decision, chosen)
    return chosen


def build_solution(
    request: RawLinkRequest,
    decision: RawLinkerDecision,
    candidates: Sequence[RawCellCandidate],
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawCellCandidate]]:
    chosen = validate_decision(request, decision, candidates)
    names: dict[str, str] = {}
    frames: dict[str, pd.DataFrame] = {}
    table_to_var: dict[str, str] = {}
    for candidate in chosen:
        if candidate.table_id not in table_to_var:
            var = f"df{len(table_to_var) + 1}"
            table_to_var[candidate.table_id] = var
            names[var] = candidate.table_id
            frames[var] = load_frame(candidate.table_id)
    terms = [candidate.query(table_to_var[candidate.table_id], request.value_transform) for candidate in chosen]
    if request.operation == "direct":
        query = terms[0]
    elif request.operation == "diff":
        query = f"{terms[0]} - {terms[1]}"
    elif request.operation == "sum":
        query = " + ".join(terms)
    elif request.operation == "avg":
        query = f"({' + '.join(terms)}) / {len(terms)}"
    elif request.operation == "ratio":
        query = f"({terms[0]}) / ({terms[1]})"
    else:  # pragma: no cover - Literal keeps this unreachable
        raise RawTableLinkError(f"unsupported operation {request.operation}")

    first = chosen[0]
    solution = PandasSolution(
        table_variable=table_to_var[first.table_id],
        target_row=str(first.row_position),
        target_column=first.column,
        source_unit=first.source_unit,
        target_unit=decision.target_unit if decision.target_unit != "unknown" else request.target_unit,
        pandas_query=query,
    )
    return solution, frames, names, chosen


def build_ratio_solution(
    request: RawLinkRequest,
    decision: RawRatioDecision,
    candidates: Sequence[RawLinkedCandidate],
) -> tuple[PandasSolution, dict[str, pd.DataFrame], dict[str, str], list[RawLinkedCandidate]]:
    selections = validate_ratio_decision(request, decision, candidates)
    chosen = [candidate for _, numerator, denominator in selections for candidate in [*numerator, *denominator]]
    names: dict[str, str] = {}
    frames: dict[str, pd.DataFrame] = {}
    table_to_var: dict[str, str] = {}
    for candidate in chosen:
        for table_id in _candidate_table_ids(candidate):
            if table_id not in table_to_var:
                var = f"df{len(table_to_var) + 1}"
                table_to_var[table_id] = var
                names[var] = table_id
                frames[var] = load_frame(table_id)

    def side_expr(side: Sequence[RawLinkedCandidate]) -> str:
        terms = [_candidate_query(candidate, table_to_var, request.value_transform) for candidate in side]
        if len(terms) == 1:
            return terms[0]
        return "(" + " + ".join(terms) + ")"

    ratio_terms: list[str] = []
    for _, numerator, denominator in selections:
        ratio_terms.append(f"({side_expr(numerator)}) / ({side_expr(denominator)})")
    if request.ratio_aggregate == "avg":
        query = f"({' + '.join(ratio_terms)}) / {len(ratio_terms)}"
    else:
        query = ratio_terms[0]
    target_unit = decision.target_unit if decision.target_unit != "unknown" else request.target_unit
    if target_unit == "percent":
        query = f"({query}) * 100"

    first_table_id, first_row, first_column, first_unit = _candidate_first_cell(chosen[0])
    solution = PandasSolution(
        table_variable=table_to_var[first_table_id],
        target_row=str(first_row),
        target_column=first_column,
        source_unit=first_unit,  # type: ignore[arg-type]
        target_unit=target_unit,  # type: ignore[arg-type]
        pandas_query=query,
    )
    return solution, frames, names, chosen


async def aprepare_raw_table_linker(
    state: Mapping[str, Any],
    *,
    use_planner: bool = False,
    planner_thinking: bool = False,
    use_ratio_groups: bool = False,
) -> dict[str, Any]:
    """Prepare a validated raw-table plan for graph execution."""
    request, reason = build_request(state)
    if request is None:
        raise RawTableLinkError(reason)
    candidate_limit = 32 if request.operation == "ratio" else 12
    if request.operation == "ratio" and use_ratio_groups:
        candidates, cand_diag = build_ratio_candidates(
            request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            cell_limit_per_slot=max(candidate_limit, 80),
        )
    else:
        candidates, cand_diag = build_candidates(
            request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            limit_per_slot=candidate_limit,
        )
    if request.operation == "ratio":
        missing_candidate_slots = [
            slot.key for slot in request.slots
            if not any(candidate.slot_key == slot.key for candidate in candidates)
        ]
        if missing_candidate_slots:
            raise RawTableLinkError(f"missing ratio candidates for slots {missing_candidate_slots}")
        if not candidates:
            raise RawTableLinkError("no raw ratio candidates")
        if not use_planner:
            raise RawTableLinkError("ratio raw linker requires planner")
        decision_source = "ratio_candidate_planner"
        ratio_diag: dict[str, Any] = {}
        use_option_surface = use_ratio_groups or _prefer_ratio_option_surface(request)
        if use_option_surface:
            options, option_diag = build_ratio_options(request, candidates, max_options_per_side=6)
            if use_ratio_groups and option_diag["missing_options"]:
                raise RawTableLinkError(f"missing ratio options for {option_diag['missing_options']}")
            option_decision = (
                deterministic_ratio_option_decision(request, options)
                if not option_diag["missing_options"]
                else RawRatioOptionDecision(
                    supported=False,
                    operation="ratio",
                    reason=f"missing ratio options for {option_diag['missing_options']}",
                )
            )
            if option_decision.supported:
                decision_source = "ratio_option_deterministic"
                ratio_decision = ratio_decision_from_options(request, option_decision, options)
            else:
                if use_ratio_groups:
                    option_decision = await aplan_raw_ratio_options(
                        question=str(state.get("question") or ""),
                        request=request,
                        options=options,
                        planner_thinking=planner_thinking,
                    )
                    decision_source = "ratio_option_planner"
                    ratio_decision = ratio_decision_from_options(request, option_decision, options)
                else:
                    ratio_decision = await aplan_raw_ratio_linker(
                        question=str(state.get("question") or ""),
                        request=request,
                        candidates=candidates,
                        planner_thinking=planner_thinking,
                    )
            ratio_diag = {
                "option_summary": option_diag,
                "options": [option.model_dump() for option in options],
                "option_decision": option_decision.model_dump(),
            }
        else:
            ratio_decision = await aplan_raw_ratio_linker(
                question=str(state.get("question") or ""),
                request=request,
                candidates=candidates,
                planner_thinking=planner_thinking,
            )
        solution, frames, names, chosen = build_ratio_solution(request, ratio_decision, candidates)
        return {
            "solution": solution,
            "frames": frames,
            "names": names,
            "table_ids": list(dict.fromkeys(
                table_id for candidate in chosen for table_id in _candidate_table_ids(candidate)
            )),
            "diag": {
                "done": True,
                "request": request.model_dump(),
                "candidate_summary": cand_diag,
                "decision_source": decision_source,
                "decision": ratio_decision.model_dump(),
                "chosen": [candidate.model_dump() for candidate in chosen],
                **ratio_diag,
            },
        }

    deterministic = deterministic_decision(request, candidates)
    solution_request = request
    solution_candidates = candidates
    solution_cand_diag = cand_diag
    search_plan: RawSearchPlan | None = None
    semantic_plan: RawSemanticPlan | None = None
    semantic_decision: RawLinkerDecision | None = None
    expanded_cand_diag: dict[str, Any] | None = None
    search_expansion_used = False
    decision_source = "deterministic"
    decision = deterministic
    if not deterministic.supported:
        if not use_planner:
            if cand_diag["missing_slots"]:
                raise RawTableLinkError(f"missing candidates for slots {cand_diag['missing_slots']}")
            if not candidates:
                raise RawTableLinkError("no raw cell candidates")
            raise RawTableLinkError(f"deterministic raw linker: {deterministic.reason}")
        decision_source = "candidate_planner"
        search_plan = await aplan_raw_search(
            question=str(state.get("question") or ""),
            request=request,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
            planner_thinking=planner_thinking,
        )
        expanded_request = request_with_search_plan(request, search_plan)
        expanded_candidates, expanded_cand_diag = (
            (candidates, cand_diag)
            if expanded_request == request
            else build_candidates(
                expanded_request,
                table_ids=list(state.get("table_ids") or []),
                shortlist=list(state.get("shortlist") or []),
            )
        )
        if search_expansion_adds_slot_coverage(
            request, search_plan, candidates, expanded_candidates,
        ):
            solution_request = expanded_request
            solution_candidates = expanded_candidates
            solution_cand_diag = expanded_cand_diag
            search_expansion_used = True
            decision_source = "search_expanded_candidate_planner"
        decision = await aplan_raw_table_linker(
            question=str(state.get("question") or ""),
            request=solution_request,
            candidates=solution_candidates,
            planner_thinking=planner_thinking,
        )
        decision = normalize_planner_decision(solution_request, decision)
    solution, frames, names, chosen = build_solution(solution_request, decision, solution_candidates)
    return {
        "solution": solution,
        "frames": frames,
        "names": names,
        "table_ids": list(dict.fromkeys(candidate.table_id for candidate in chosen)),
        "diag": {
            "done": True,
            "request": solution_request.model_dump(),
            "initial_request": request.model_dump(),
            "candidate_summary": solution_cand_diag,
            "initial_candidate_summary": cand_diag,
            "decision_source": decision_source,
            "deterministic_decision": deterministic.model_dump(),
            "search_plan": search_plan.model_dump() if search_plan else None,
            "search_expansion_used": search_expansion_used,
            "expanded_candidate_summary": expanded_cand_diag,
            "semantic_plan": semantic_plan.model_dump() if semantic_plan else None,
            "semantic_decision": semantic_decision.model_dump() if semantic_decision else None,
            "decision": decision.model_dump(),
            "chosen": [candidate.model_dump() for candidate in chosen],
        },
    }


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
