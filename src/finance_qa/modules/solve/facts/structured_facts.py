"""Structured fact solver over the normalized main-statement fact table.

This is deliberately narrower than the raw-grid codegen path. It handles the
class where the current solver fails most often: derived metrics over the main
VAS statements, especially selection questions across years or companies. The
LLM may choose a plan, but it never writes executable code or SQL; all formulae
and data access live here.
"""
from __future__ import annotations

import math
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from statistics import median
from typing import Annotated, Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finance_qa.core.llm import get_chat_model
from finance_qa.core.paths import DATA_DIR, LONG_FORMAT_PATH, TABLE_METADATA_PATH
from finance_qa.modules.solve.common.units import conversion_factor, detect_unit, unit_from_hint
from finance_qa.modules.tools.numeric import parse_number


Operation = Literal[
    "lookup", "ratio", "growth", "diff", "avg", "median",
    "argmax", "argmin", "conditional_select", "unsupported",
]
Axis = Literal["year", "ticker", ""]
Order = Literal["max", "min", ""]
Relation = Literal["gt", "ge", "lt", "le", "eq", ""]
DocType = Literal["consolidated", "separate", "unknown"]
FilterValueSource = Literal["literal", "median"]
MissingPolicy = Literal["fail", "skip"]
Expression = Literal[
    "",
    "net_profit_minus_cfo",
    "stress_interest_coverage",
    "inventory_days_excess_release",
]
PlannerOperation = Literal["argmax", "argmin", "conditional_select", "unsupported"]
PlannerSelectionOperation = Literal["argmax", "argmin"]
PlannerAxis = Literal["year", "ticker", ""]
PlannerConcreteAxis = Literal["year", "ticker"]
PlannerOrder = Literal["max", "min", ""]
PlannerSelectionOrder = Literal["max", "min"]
PlannerRelation = Literal["gt", "ge", "lt", "le", "eq"]
PlannerTargetUnit = Literal[
    "",
    "vnd",
    "thousand_vnd",
    "million_vnd",
    "billion_vnd",
    "hundred_billion_vnd",
    "trillion_vnd",
    "percent",
    "ratio",
    "count",
    "year",
    "unknown",
]

_NON_WORD = re.compile(r"[^a-z0-9]+")


def _norm(text: object) -> str:
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def _contains(norm_text: str, norm_alias: str) -> bool:
    return bool(norm_alias and f" {norm_alias} " in f" {norm_text} ")


@dataclass(frozen=True)
class PrimitiveMetric:
    key: str
    statement_type: str
    ma_so: str
    unit: str = "vnd"
    aliases: tuple[str, ...] = ()


PRIMITIVES: dict[str, PrimitiveMetric] = {
    "net_revenue": PrimitiveMetric(
        "net_revenue", "income_statement", "10",
        aliases=("doanh thu thuần", "dtt", "net revenue"),
    ),
    "cogs": PrimitiveMetric(
        "cogs", "income_statement", "11",
        aliases=("giá vốn hàng bán", "gia von", "cogs"),
    ),
    "gross_profit": PrimitiveMetric(
        "gross_profit", "income_statement", "20",
        aliases=("lợi nhuận gộp", "gross profit"),
    ),
    "interest_expense": PrimitiveMetric(
        "interest_expense", "income_statement", "23",
        aliases=("chi phí lãi vay", "interest expense"),
    ),
    "financial_income": PrimitiveMetric(
        "financial_income", "income_statement", "21",
        aliases=("doanh thu hoạt động tài chính",),
    ),
    "profit_before_tax": PrimitiveMetric(
        "profit_before_tax", "income_statement", "50",
        aliases=("lợi nhuận trước thuế", "lntt", "pbt"),
    ),
    "net_profit": PrimitiveMetric(
        "net_profit", "income_statement", "60",
        aliases=("lợi nhuận sau thuế", "lnst", "lợi nhuận ròng", "npat"),
    ),
    "cfo": PrimitiveMetric(
        "cfo", "cash_flow", "20",
        aliases=(
            "cfo", "lưu chuyển tiền thuần từ hoạt động kinh doanh",
            "dòng tiền thuần từ hoạt động kinh doanh",
        ),
    ),
    "current_assets": PrimitiveMetric(
        "current_assets", "balance_sheet", "100",
        aliases=("tài sản ngắn hạn",),
    ),
    "cash_and_equivalents": PrimitiveMetric(
        "cash_and_equivalents", "balance_sheet", "110",
        aliases=("tiền và các khoản tương đương tiền", "tiền cuối năm"),
    ),
    "inventory": PrimitiveMetric(
        "inventory", "balance_sheet", "140",
        aliases=("hàng tồn kho", "giá trị hàng tồn kho"),
    ),
    "total_assets": PrimitiveMetric(
        "total_assets", "balance_sheet", "270",
        aliases=("tổng tài sản", "tổng cộng tài sản"),
    ),
    "liabilities": PrimitiveMetric(
        "liabilities", "balance_sheet", "300",
        aliases=("nợ phải trả", "tổng nợ phải trả"),
    ),
    "current_liabilities": PrimitiveMetric(
        "current_liabilities", "balance_sheet", "310",
        aliases=("nợ ngắn hạn", "nợ phải trả ngắn hạn"),
    ),
    "equity": PrimitiveMetric(
        "equity", "balance_sheet", "400",
        aliases=("vốn chủ sở hữu", "tổng vốn chủ sở hữu", "vcsh"),
    ),
}

DERIVED_ALIASES: dict[str, tuple[str, ...]] = {
    "de_ratio": (
        "d/e", "tỷ số nợ trên vốn chủ sở hữu",
        "nợ phải trả trên vốn chủ sở hữu",
    ),
    "debt_to_assets": (
        "nợ phải trả trên tổng tài sản",
        "nợ trên tổng tài sản",
        "tỷ lệ nợ trên tổng tài sản",
    ),
    "current_ratio": ("hệ số thanh toán hiện hành", "current ratio"),
    "quick_ratio": ("hệ số thanh toán nhanh", "quick ratio"),
    "working_capital": ("vốn lưu động ròng",),
    "gross_margin": (
        "biên lợi nhuận gộp",
        "tỷ suất lợi nhuận gộp",
        "lợi nhuận gộp trên doanh thu thuần",
    ),
    "cogs_to_revenue": (
        "tỷ lệ giá vốn hàng bán trên doanh thu thuần",
        "giá vốn hàng bán trên doanh thu thuần",
    ),
    "net_margin": (
        "biên lợi nhuận ròng",
        "tỷ suất lợi nhuận ròng",
        "lợi nhuận sau thuế trên doanh thu thuần",
    ),
    "pretax_margin": (
        "tỷ suất lợi nhuận trước thuế",
        "lợi nhuận trước thuế trên doanh thu thuần",
        "lợi nhuận trước thuế trên doanh thu",
    ),
    "roe": ("roe", "lợi nhuận sau thuế trên vốn chủ sở hữu"),
    "roa": ("roa", "tỷ suất sinh lời trên tổng tài sản"),
    "net_profit_to_total_assets": (
        "lợi nhuận sau thuế trên tổng tài sản",
        "lợi nhuận sau thuế trên tổng tài sản cuối năm",
    ),
    "interest_coverage": (
        "hệ số khả năng thanh toán lãi vay",
        "hệ số thanh toán lãi vay", "interest coverage", "icr",
        "tỷ lệ tổng của lợi nhuận trước thuế và chi phí lãi vay trên chi phí lãi vay",
        "lợi nhuận trước thuế và chi phí lãi vay trên chi phí lãi vay",
    ),
    "cfo_to_net_profit": (
        "cfo/lnst", "cfo trên lnst",
        "hệ số chuyển đổi lợi nhuận",
        "tỷ lệ dòng tiền hoạt động trên lnst",
        "dòng tiền hoạt động trên lợi nhuận sau thuế",
        "dòng tiền kinh doanh trên lợi nhuận sau thuế",
    ),
    "cfo_to_profit_before_tax": (
        "dòng tiền thuần từ hoạt động kinh doanh trên lợi nhuận trước thuế",
        "dòng tiền hoạt động trên lợi nhuận trước thuế",
        "cfo trên lợi nhuận trước thuế",
        "cfo/lntt",
    ),
    "cfo_to_revenue": (
        "cfo/dtt", "cfo trên doanh thu thuần",
        "dòng tiền hoạt động trên doanh thu thuần",
        "dòng tiền thuần từ hoạt động kinh doanh trên doanh thu thuần",
    ),
    "cfo_to_current_liabilities": ("dòng tiền hoạt động trên nợ ngắn hạn",),
    "inventory_to_assets": ("hàng tồn kho trên tổng tài sản",),
    "inventory_days": ("số ngày hàng tồn kho", "vòng quay hàng tồn kho", "doh"),
    "current_liabilities_to_equity": (
        "tỷ lệ nợ ngắn hạn trên vốn chủ sở hữu",
        "tỷ số nợ ngắn hạn trên vốn chủ sở hữu",
        "nợ ngắn hạn trên vốn chủ sở hữu",
    ),
}

METRIC_KEYS = tuple(PRIMITIVES) + tuple(DERIVED_ALIASES)

EXPRESSION_ALIASES: dict[str, tuple[str, ...]] = {
    "net_profit_minus_cfo": (
        "lnst chưa chuyển hóa thành cfo",
        "lợi nhuận sau thuế chưa chuyển hóa thành cfo",
        "phần lnst chưa chuyển hóa thành cfo",
    ),
    "stress_interest_coverage": (
        "ebit proxy",
        "chi phí lãi vay giảm 15%",
        "hệ số khả năng thanh toán lãi vay theo kịch bản",
    ),
    "inventory_days_excess_release": (
        "giải phóng ước tính",
        "giảm số ngày tồn kho về đúng trung vị",
    ),
}
EXPRESSION_KEYS = tuple(EXPRESSION_ALIASES)
PlannerMetric = Literal[*METRIC_KEYS]
PlannerExpression = Literal[*EXPRESSION_KEYS]
PlannerMeasure = Literal["", *METRIC_KEYS, *EXPRESSION_KEYS]
PlannerMeasureNoEmpty = Literal[*METRIC_KEYS, *EXPRESSION_KEYS]
PlannerFilterMeasure = Literal[*METRIC_KEYS, *EXPRESSION_KEYS]
PlannerAnswerMetricNoEmpty = Literal["year", *METRIC_KEYS]
PlannerAnswerMetric = Literal["", "year", *METRIC_KEYS]
PlannerAnswerExpression = Literal["", *EXPRESSION_KEYS]

METRIC_SCHEMA_DESCRIPTION = (
    "Catalog metric key. Direct VAS facts: net_revenue, cogs, gross_profit, "
    "interest_expense, financial_income, profit_before_tax, net_profit, cfo, current_assets, "
    "cash_and_equivalents, inventory, total_assets, liabilities, "
    "current_liabilities, equity. Derived metrics supported by the executor: "
    "de_ratio=liabilities/equity; debt_to_assets=liabilities/total_assets; "
    "current_ratio=current_assets/current_liabilities; "
    "quick_ratio=(current_assets-inventory)/current_liabilities; "
    "working_capital=current_assets-current_liabilities; "
    "gross_margin=gross_profit/net_revenue; "
    "cogs_to_revenue=cogs/net_revenue; "
    "net_margin=net_profit/net_revenue; roe=net_profit/equity; "
    "pretax_margin=profit_before_tax/net_revenue; "
    "roa=net_profit/average_total_assets; "
    "net_profit_to_total_assets=net_profit/ending_total_assets; "
    "interest_coverage=(profit_before_tax+interest_expense)/interest_expense; "
    "cfo_to_net_profit=cfo/net_profit; cfo_to_revenue=cfo/net_revenue; "
    "cfo_to_profit_before_tax=cfo/profit_before_tax; "
    "cfo_to_current_liabilities=cfo/current_liabilities; "
    "inventory_to_assets=inventory/total_assets; inventory_days=inventory/(cogs/365); "
    "current_liabilities_to_equity=current_liabilities/equity."
)
EXPRESSION_SCHEMA_DESCRIPTION = (
    "Whitelisted expression key. net_profit_minus_cfo returns net_profit-cfo; "
    "stress_interest_coverage returns a scenario interest coverage ratio; "
    "inventory_days_excess_release returns estimated money released by reducing "
    "inventory_days to the candidate-set median."
)

_RATIO_METRICS = frozenset(DERIVED_ALIASES) - frozenset({"working_capital"})
_MONEY_UNITS = frozenset({
    "vnd",
    "thousand_vnd",
    "million_vnd",
    "billion_vnd",
    "hundred_billion_vnd",
    "trillion_vnd",
})


def canonical_metric(text: str) -> str:
    """Map planner/user text to a supported metric key."""
    raw = str(text or "").strip()
    if raw in METRIC_KEYS:
        return raw
    norm = _norm(raw)
    for key, metric in PRIMITIVES.items():
        if norm == _norm(key) or any(_contains(norm, _norm(a)) for a in metric.aliases):
            return key
    for key, aliases in DERIVED_ALIASES.items():
        if norm == _norm(key) or any(_contains(norm, _norm(a)) for a in aliases):
            return key
    return ""


def canonical_measure(text: str) -> str:
    """Map planner/user text to a metric or whitelisted expression key."""
    raw = str(text or "").strip()
    if raw in EXPRESSION_KEYS:
        return raw
    metric = canonical_metric(text)
    if metric:
        return metric
    norm = _norm(raw)
    for key, aliases in EXPRESSION_ALIASES.items():
        if norm == _norm(key) or any(_contains(norm, _norm(a)) for a in aliases):
            return key
    return ""


def metric_source_unit(key: str) -> str:
    """Natural unit of a catalog metric before the question's requested scaling."""
    key = canonical_measure(key)
    if key in PRIMITIVES:
        return PRIMITIVES[key].unit
    if key == "working_capital":
        return "vnd"
    if key in _RATIO_METRICS:
        return "ratio"
    if key in {"net_profit_minus_cfo", "inventory_days_excess_release"}:
        return "vnd"
    if key == "stress_interest_coverage":
        return "ratio"
    if key == "year":
        return "year"
    return "unknown"


def metrics_in_text(text: str) -> list[str]:
    """Supported metrics mentioned in text, ordered by first alias occurrence."""
    norm = _norm(text)
    hits: list[tuple[int, str]] = []
    seen: set[str] = set()
    for key, metric in PRIMITIVES.items():
        aliases = (_norm(key), *(_norm(a) for a in metric.aliases))
        positions = [norm.find(a) for a in aliases if a and norm.find(a) >= 0]
        if positions and key not in seen:
            hits.append((min(positions), key))
            seen.add(key)
    for key, aliases0 in DERIVED_ALIASES.items():
        aliases = (_norm(key), *(_norm(a) for a in aliases0))
        positions = [norm.find(a) for a in aliases if a and norm.find(a) >= 0]
        if positions and key not in seen:
            hits.append((min(positions), key))
            seen.add(key)
    return [key for _, key in sorted(hits)]


class MetricFilter(BaseModel):
    """One deterministic filter over a candidate element."""

    metric: str = Field(default="")
    relation: Relation = Field(default="")
    value: float | None = Field(default=None)
    value_source: FilterValueSource = Field(default="literal")

    @field_validator("metric")
    @classmethod
    def _metric_key(cls, value):
        return canonical_measure(value) or str(value or "")


class StructuredPlan(BaseModel):
    """A bounded plan the deterministic fact executor can run."""

    supported: bool = Field(default=True)
    operation: Operation = Field(default="unsupported")
    axis: Axis = Field(default="")
    tickers: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    doc_type: DocType = Field(default="unknown")
    selector_metric: str = Field(default="")
    selector_order: Order = Field(default="")
    answer_metric: str = Field(default="")
    filter_metric: str = Field(default="")
    filter_relation: Relation = Field(default="")
    filter_value: float | None = Field(default=None)
    filters: list[MetricFilter] = Field(default_factory=list)
    year_offset: int = Field(default=0)
    answer_expression: Expression = Field(default="")
    missing_policy: MissingPolicy = Field(default="fail")
    scenario_factor: float | None = Field(default=None)
    round_digits: int | None = Field(default=None)
    target_unit: str = Field(default="")
    reason: str = Field(default="")

    @field_validator("tickers", mode="before")
    @classmethod
    def _tickers(cls, value):
        return [str(v).upper().strip() for v in (value or []) if str(v).strip()]

    @field_validator("years", mode="before")
    @classmethod
    def _years(cls, value):
        return sorted({int(v) for v in (value or []) if str(v).strip().isdigit()})

    @field_validator("selector_metric", "answer_metric", "filter_metric")
    @classmethod
    def _metric_key(cls, value):
        return canonical_measure(value) or str(value or "")


class PlannerMetricAnswer(BaseModel):
    """Return a catalog metric for the selected candidate."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["metric"] = Field(default="metric")
    metric: PlannerAnswerMetricNoEmpty = Field(description=METRIC_SCHEMA_DESCRIPTION)


class PlannerExpressionAnswer(BaseModel):
    """Return a whitelisted expression for the selected candidate."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["expression"] = Field(default="expression")
    expression: PlannerExpression = Field(description=EXPRESSION_SCHEMA_DESCRIPTION)


PlannerAnswer = Annotated[
    PlannerMetricAnswer | PlannerExpressionAnswer,
    Field(discriminator="kind"),
]


class PlannerMetricFilter(BaseModel):
    """A candidate filter in the LLM-facing selection-plan schema."""

    model_config = ConfigDict(extra="forbid")

    metric: PlannerFilterMeasure = Field(
        description=(
            "Catalog metric or whitelisted expression used to filter candidates. "
            + METRIC_SCHEMA_DESCRIPTION + " " + EXPRESSION_SCHEMA_DESCRIPTION
        )
    )
    relation: PlannerRelation = Field(
        description="Comparison relation applied to the filter value."
    )
    value: float | None = Field(
        default=None,
        description="Literal threshold when value_source is literal.",
    )
    value_source: FilterValueSource = Field(
        default="literal",
        description="Use median to compare against the candidate-set median.",
    )


class StructuredSelectionPlan(BaseModel):
    """Schema for filter -> rank candidate -> return metric/expression selection."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["selection"] = Field(default="selection")
    operation: PlannerSelectionOperation = Field(
        description=(
            "Selection operation for ranking candidates. Use argmax/argmin whenever "
            "the question chooses the largest/smallest selector_metric. Filters are "
            "represented separately; there is no separate conditional operation."
        ),
    )
    axis: PlannerConcreteAxis = Field(
        description="Candidate axis: year for selecting a year, ticker for selecting a company.",
    )
    tickers: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    doc_type: DocType = Field(default="unknown")
    selector_metric: PlannerMeasureNoEmpty = Field(
        description=(
            "Metric/expression used to rank candidates. "
            + METRIC_SCHEMA_DESCRIPTION + " " + EXPRESSION_SCHEMA_DESCRIPTION
        ),
    )
    selector_order: PlannerSelectionOrder = Field(
        description="max for argmax, min for argmin.",
    )
    answer: PlannerAnswer = Field(
        description=(
            "Exactly one answer branch: metric returns a catalog metric/year; "
            "expression returns a whitelisted expression."
        ),
    )
    filters: list[PlannerMetricFilter] = Field(
        default_factory=list,
        description="Candidate filters; ticker/year/doc_type are scope fields, not filters.",
    )
    year_offset: int = Field(
        default=0,
        description="Offset from selected year to answer year; only valid on year axis.",
    )
    missing_policy: MissingPolicy = Field(default="fail")
    scenario_factor: float | None = Field(default=None)
    round_digits: int | None = Field(default=None)
    target_unit: PlannerTargetUnit = Field(default="")

    @field_validator("tickers", mode="before")
    @classmethod
    def _tickers(cls, value):
        return [str(v).upper().strip() for v in (value or []) if str(v).strip()]

    @field_validator("years", mode="before")
    @classmethod
    def _years(cls, value):
        return sorted({int(v) for v in (value or []) if str(v).strip().isdigit()})

    @model_validator(mode="after")
    def _selection_contract(self):
        if self.year_offset and self.axis != "year":
            raise ValueError("year_offset only applies to year selections")
        return self

    def to_structured_plan(self) -> StructuredPlan:
        """Convert the narrow planner schema into the executor schema."""
        answer_metric = ""
        answer_expression = ""
        if isinstance(self.answer, PlannerMetricAnswer):
            answer_metric = self.answer.metric
        elif isinstance(self.answer, PlannerExpressionAnswer):
            answer_expression = self.answer.expression
        return StructuredPlan(
            supported=True,
            operation=self.operation,
            axis=self.axis,
            tickers=self.tickers,
            years=self.years,
            doc_type=self.doc_type,
            selector_metric=self.selector_metric,
            selector_order=self.selector_order,
            answer_metric=answer_metric,
            filters=[
                MetricFilter(
                    metric=flt.metric,
                    relation=flt.relation,
                    value=flt.value,
                    value_source=flt.value_source,
                )
                for flt in self.filters
                if not (
                    flt.value is None
                    and flt.value_source == "literal"
                    and flt.metric == self.selector_metric
                )
                and not (
                    flt.metric == self.selector_metric
                    and flt.relation == "eq"
                )
            ],
            year_offset=self.year_offset,
            answer_expression=answer_expression,
            missing_policy=self.missing_policy,
            scenario_factor=self.scenario_factor,
            round_digits=self.round_digits,
            target_unit=self.target_unit,
        )


class UnsupportedStructuredPlan(BaseModel):
    """Explicit branch for questions outside the structured fact schema."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["unsupported"] = Field(default="unsupported")
    reason: str = Field(description="Why the question cannot be expressed by the schema.")

    def to_structured_plan(self) -> StructuredPlan:
        return StructuredPlan(
            supported=False,
            operation="unsupported",
            reason=self.reason,
        )


PlannerPlan = Annotated[
    StructuredSelectionPlan | UnsupportedStructuredPlan,
    Field(discriminator="kind"),
]


class StructuredPlannerOutput(BaseModel):
    """LLM-facing root schema: exactly one supported plan or unsupported reason."""

    model_config = ConfigDict(extra="forbid")

    plan: PlannerPlan

    def to_structured_plan(self) -> StructuredPlan:
        return self.plan.to_structured_plan()


@dataclass(frozen=True)
class Fact:
    value: float
    table_id: str
    row: dict[str, Any]


class StructuredFactError(RuntimeError):
    """Unsupported plan or missing fact."""


_BANK_LABEL_FALLBACK_METRICS = frozenset({
    "total_assets",
    "liabilities",
    "equity",
    "interest_expense",
    "profit_before_tax",
    "net_profit",
    "cfo",
})
_NON_VALUE_COLUMNS = frozenset({"stt", "tm", "thuyet minh", "ma so", "mau so"})
_LEADING_LABEL_CODE = re.compile(r"^(?:[ivxlcdm]+|\d+|[a-z])\s+")


def _semantic_label(label: object) -> str:
    text = _norm(label)
    for _ in range(3):
        stripped = _LEADING_LABEL_CODE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text


def _bank_label_matches(metric_key: str, label: object) -> bool:
    """Conservative row-label matcher for bank primary statements without VAS mã số."""
    core = _semantic_label(label)
    if metric_key == "total_assets":
        return core in {"tong tai san co", "tong tai san", "tong cong tai san"}
    if metric_key == "liabilities":
        return core == "tong no phai tra"
    if metric_key == "equity":
        return core in {"von chu so huu", "tong von chu so huu", "von va cac quy"}
    if metric_key == "interest_expense":
        return core.startswith("chi phi lai va cac chi phi tuong tu") or core == "chi phi lai"
    if metric_key == "profit_before_tax":
        return core in {"tong loi nhuan truoc thue", "loi nhuan truoc thue"}
    if metric_key == "net_profit":
        return core.startswith("loi nhuan sau thue") and "truoc" not in core
    if metric_key == "cfo":
        return (
            core.startswith("luu chuyen tien thuan tu hoat dong kinh doanh")
            and "truoc nhung thay doi" not in core
        )
    return False


def _bank_label_column(df) -> str:
    for col in df.columns:
        if "chi tieu" in _norm(col):
            return col

    best_col = df.columns[0]
    best_score = -1
    for col in list(df.columns)[:3]:
        if _norm(col) in _NON_VALUE_COLUMNS:
            continue
        score = 0
        for value in df[col].head(80):
            text = _norm(value)
            if len(text) >= 3 and parse_number(str(value)) is None:
                score += 1
        if score > best_score:
            best_col, best_score = col, score
    return best_col


def _bank_period_columns(df, meta: dict[str, Any], label_col: str) -> list[str]:
    raw_periods = {str(col).strip() for col in (meta.get("period_columns_raw") or [])}
    exact = [col for col in df.columns if str(col).strip() in raw_periods]
    if exact:
        return exact

    period_cols: list[str] = []
    for col in df.columns:
        norm_col = _norm(col)
        if col == label_col or norm_col in _NON_VALUE_COLUMNS:
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", norm_col) or "nam" in norm_col or "31 12" in norm_col:
            period_cols.append(col)
    return period_cols


class StatementFactStore:
    """DuckDB-backed access to ``long_format.parquet``."""

    def __init__(self, path=LONG_FORMAT_PATH):
        import duckdb

        self.path = str(path)
        self._metadata_by_scope: dict[tuple[str, int, str], list[dict[str, Any]]] | None = None
        self.conn = duckdb.connect(database=":memory:")
        escaped = self.path.replace("'", "''")
        self.conn.execute(
            "CREATE VIEW statement_facts AS "
            f"SELECT * FROM read_parquet('{escaped}')"
        )

    def rows(
        self,
        *,
        ticker: str,
        year: int,
        doc_type: str,
        statement_type: str,
        ma_so: str,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [ticker.upper(), int(year), statement_type, str(ma_so)]
        where = [
            "ticker = ?", "year = ?", "statement_type = ?", "ma_so = ?",
        ]
        if doc_type in {"consolidated", "separate"}:
            where.append("doc_type = ?")
            params.append(doc_type)
        sql = (
            "SELECT report_id, ticker, year, doc_type, statement_type, "
            "statement_subtype, table_pos, ma_so, label, note_id, period, value "
            "FROM statement_facts WHERE "
            + " AND ".join(where)
        )
        return self.conn.execute(sql, params).fetch_df().to_dict("records")

    def value(
        self,
        *,
        ticker: str,
        year: int,
        doc_type: str,
        metric: PrimitiveMetric,
        period_kind: str = "end",
    ) -> Fact:
        rows = self.rows(
            ticker=ticker, year=year, doc_type=doc_type,
            statement_type=metric.statement_type, ma_so=metric.ma_so,
        )
        ranked = sorted(
            (row for row in rows if _finite(row.get("value"))),
            key=lambda row: _row_rank(row, year, period_kind, doc_type),
        )
        if not ranked:
            ranked = self._bank_label_fallback_rows(
                ticker=ticker,
                year=year,
                doc_type=doc_type,
                metric=metric,
                period_kind=period_kind,
            )
        if not ranked:
            raise StructuredFactError(
                f"missing fact: {ticker} {year} {doc_type} "
                f"{metric.statement_type} ma_so={metric.ma_so}"
            )
        row = ranked[0]
        if doc_type == "unknown" and row.get("doc_type") != "consolidated":
            raise StructuredFactError(
                f"missing consolidated fact: {ticker} {year} "
                f"{metric.statement_type} ma_so={metric.ma_so}"
            )
        table_id = f"{row['report_id']}|{int(row['table_pos'])}"
        return Fact(float(row["value"]), table_id, row)

    def _metadata_index(self) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
        if self._metadata_by_scope is not None:
            return self._metadata_by_scope
        by_scope: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
        with TABLE_METADATA_PATH.open(encoding="utf-8") as fp:
            for line in fp:
                rec = json.loads(line)
                ticker = str(rec.get("ticker") or "").upper()
                year = rec.get("year")
                statement_type = str(rec.get("statement_type") or "")
                if not ticker or not year or statement_type not in {"balance_sheet", "income_statement", "cash_flow"}:
                    continue
                by_scope.setdefault((ticker, int(year), statement_type), []).append(rec)
        self._metadata_by_scope = by_scope
        return by_scope

    def _bank_label_fallback_rows(
        self,
        *,
        ticker: str,
        year: int,
        doc_type: str,
        metric: PrimitiveMetric,
        period_kind: str,
    ) -> list[dict[str, Any]]:
        if metric.key not in _BANK_LABEL_FALLBACK_METRICS:
            return []
        candidates = self._metadata_index().get(
            (ticker.upper(), int(year), metric.statement_type), []
        )
        rows: list[dict[str, Any]] = []
        for meta in candidates:
            if meta.get("industry_segment") != "bank":
                continue
            if meta.get("has_ma_so_column"):
                continue
            if doc_type in {"consolidated", "separate"} and meta.get("doc_type") != doc_type:
                continue
            rows.extend(self._read_bank_label_rows(meta, metric))

        ranked = sorted(
            (row for row in rows if _finite(row.get("value"))),
            key=lambda row: _row_rank(row, year, period_kind, doc_type),
        )
        return ranked

    def _read_bank_label_rows(self, meta: dict[str, Any], metric: PrimitiveMetric) -> list[dict[str, Any]]:
        import pandas as pd

        csv_path = DATA_DIR / str(meta.get("csv_path") or "")
        if not csv_path.exists():
            return []
        try:
            df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        except Exception:
            return []
        if df.empty:
            return []

        label_col = _bank_label_column(df)
        period_cols = _bank_period_columns(df, meta, label_col)
        if not period_cols:
            return []

        out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            label = str(row.get(label_col, "")).strip()
            if not _bank_label_matches(metric.key, label):
                continue
            for period_col in period_cols:
                parsed = parse_number(str(row.get(period_col, "")))
                if parsed is None:
                    continue
                source_unit, source_where = detect_unit(
                    df, str(period_col), str(meta.get("context_page_text") or "")
                )
                source_unit = source_unit or "vnd"
                value = float(parsed) * conversion_factor(source_unit, metric.unit)
                out.append(
                    {
                        "report_id": meta["report_id"],
                        "ticker": meta["ticker"],
                        "year": int(meta["year"]),
                        "doc_type": meta["doc_type"],
                        "statement_type": meta["statement_type"],
                        "statement_subtype": meta.get("statement_subtype"),
                        "table_pos": meta["table_pos"],
                        "ma_so": metric.ma_so,
                        "label": label,
                        "note_id": meta.get("note_id") or None,
                        "period": str(period_col).strip(),
                        "value": value,
                        "fact_source": "bank_label_fallback",
                        "source_unit": source_unit,
                        "source_unit_from": source_where,
                    }
                )
        return out


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _period_kind(period: object, year: int) -> str:
    text = str(period or "").lower()
    if (
        re.search(r"(?<!\d)0?1[/.]0?1(?!\d)", text)
        or "đầu" in text
        or str(year - 1) in text
    ):
        return "begin"
    if re.search(r"(?<!\d)31[/.]12(?!\d)", text) or "cuối" in text or str(year) in text:
        return "end"
    return "current"


def _row_rank(row: dict[str, Any], year: int, wanted: str, doc_type: str) -> tuple:
    period = _period_kind(row.get("period"), year)
    label = str(row.get("label") or "").strip()
    if doc_type == "unknown":
        doc_penalty = 0 if row.get("doc_type") == "consolidated" else 1
    else:
        doc_penalty = 0 if row.get("doc_type") == doc_type else 1
    period_penalty = 0 if period == wanted else (1 if period == "current" else 2)
    label_penalty = 1 if label == str(row.get("ma_so")) else 0
    return (doc_penalty, period_penalty, label_penalty, int(row.get("table_pos") or 999))


@lru_cache(maxsize=1)
def default_store() -> StatementFactStore:
    return StatementFactStore()


class _EvalContext:
    def __init__(self, store: StatementFactStore, doc_type: str):
        self.store = store
        self.doc_type = doc_type
        self.facts: list[Fact] = []

    def primitive(self, key: str, ticker: str, year: int, period_kind: str = "end") -> float:
        metric = PRIMITIVES[key]
        fact = self.store.value(
            ticker=ticker, year=year, doc_type=self.doc_type,
            metric=metric, period_kind=period_kind,
        )
        self.facts.append(fact)
        return fact.value


def _average_primitive(ctx: _EvalContext, key: str, ticker: str, year: int) -> float:
    try:
        begin = ctx.primitive(key, ticker, year, period_kind="begin")
        end = ctx.primitive(key, ticker, year, period_kind="end")
    except StructuredFactError:
        return ctx.primitive(key, ticker, year, period_kind="end")
    return (begin + end) / 2.0


def _metric_value(ctx: _EvalContext, key: str, ticker: str, year: int) -> tuple[float, str]:
    """Return ``(value, source_unit)`` for one supported metric."""
    key = canonical_metric(key)
    if key in PRIMITIVES:
        return ctx.primitive(key, ticker, year), PRIMITIVES[key].unit
    if key == "de_ratio":
        return _divide(ctx.primitive("liabilities", ticker, year), ctx.primitive("equity", ticker, year)), "ratio"
    if key == "debt_to_assets":
        return _divide(ctx.primitive("liabilities", ticker, year), ctx.primitive("total_assets", ticker, year)), "ratio"
    if key == "current_ratio":
        return _divide(ctx.primitive("current_assets", ticker, year), ctx.primitive("current_liabilities", ticker, year)), "ratio"
    if key == "quick_ratio":
        ca = ctx.primitive("current_assets", ticker, year)
        inv = ctx.primitive("inventory", ticker, year)
        cl = ctx.primitive("current_liabilities", ticker, year)
        return _divide(ca - inv, cl), "ratio"
    if key == "working_capital":
        return ctx.primitive("current_assets", ticker, year) - ctx.primitive("current_liabilities", ticker, year), "vnd"
    if key == "gross_margin":
        return _divide(ctx.primitive("gross_profit", ticker, year), ctx.primitive("net_revenue", ticker, year)), "ratio"
    if key == "cogs_to_revenue":
        return _divide(abs(ctx.primitive("cogs", ticker, year)), ctx.primitive("net_revenue", ticker, year)), "ratio"
    if key == "net_margin":
        return _divide(ctx.primitive("net_profit", ticker, year), ctx.primitive("net_revenue", ticker, year)), "ratio"
    if key == "pretax_margin":
        return _divide(ctx.primitive("profit_before_tax", ticker, year), ctx.primitive("net_revenue", ticker, year)), "ratio"
    if key == "roe":
        return _divide(ctx.primitive("net_profit", ticker, year), _average_primitive(ctx, "equity", ticker, year)), "ratio"
    if key == "roa":
        return _divide(ctx.primitive("net_profit", ticker, year), _average_primitive(ctx, "total_assets", ticker, year)), "ratio"
    if key == "net_profit_to_total_assets":
        return _divide(ctx.primitive("net_profit", ticker, year), ctx.primitive("total_assets", ticker, year)), "ratio"
    if key == "interest_coverage":
        pbt = ctx.primitive("profit_before_tax", ticker, year)
        interest = abs(ctx.primitive("interest_expense", ticker, year))
        return _divide(abs(pbt) + interest, interest), "ratio"
    if key == "cfo_to_net_profit":
        return _divide(ctx.primitive("cfo", ticker, year), ctx.primitive("net_profit", ticker, year)), "ratio"
    if key == "cfo_to_profit_before_tax":
        return _divide(ctx.primitive("cfo", ticker, year), ctx.primitive("profit_before_tax", ticker, year)), "ratio"
    if key == "cfo_to_revenue":
        return _divide(ctx.primitive("cfo", ticker, year), ctx.primitive("net_revenue", ticker, year)), "ratio"
    if key == "cfo_to_current_liabilities":
        return _divide(ctx.primitive("cfo", ticker, year), ctx.primitive("current_liabilities", ticker, year)), "ratio"
    if key == "inventory_to_assets":
        return _divide(ctx.primitive("inventory", ticker, year), ctx.primitive("total_assets", ticker, year)), "ratio"
    if key == "inventory_days":
        return _divide(ctx.primitive("inventory", ticker, year), abs(ctx.primitive("cogs", ticker, year))) * 365, "ratio"
    if key == "current_liabilities_to_equity":
        return _divide(ctx.primitive("current_liabilities", ticker, year), ctx.primitive("equity", ticker, year)), "ratio"
    raise StructuredFactError(f"unsupported metric: {key}")


def _measure_value(
    ctx: _EvalContext,
    key: str,
    ticker: str,
    year: int,
    plan: StructuredPlan | None = None,
    selected: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Return one catalog metric or one whitelisted expression."""
    key = canonical_measure(key)
    if key == "net_profit_minus_cfo":
        return (
            ctx.primitive("net_profit", ticker, year) - ctx.primitive("cfo", ticker, year),
            "vnd",
        )
    if key == "stress_interest_coverage":
        factor = 1.0 if plan is None or plan.scenario_factor is None else float(plan.scenario_factor)
        pbt = ctx.primitive("profit_before_tax", ticker, year)
        interest = abs(ctx.primitive("interest_expense", ticker, year))
        return _divide((pbt + interest) * factor, interest), "ratio"
    if key == "inventory_days_excess_release":
        targets = (selected or {}).get("filter_targets") or {}
        median_days = targets.get("inventory_days")
        if median_days is None:
            raise StructuredFactError("inventory_days_excess_release needs inventory_days median")
        days, _ = _metric_value(ctx, "inventory_days", ticker, year)
        cogs = abs(ctx.primitive("cogs", ticker, year))
        return max(0.0, days - float(median_days)) / 365.0 * cogs, "vnd"
    if canonical_metric(key):
        return _metric_value(ctx, key, ticker, year)
    raise StructuredFactError(f"unsupported measure: {key}")


def _divide(num: float, den: float) -> float:
    if not _finite(den) or abs(float(den)) < 1e-12:
        raise StructuredFactError("division by zero")
    return float(num) / float(den)


def _passes(value: float, relation: str, target: float | None) -> bool:
    if relation == "" or target is None:
        return True
    if relation == "gt":
        return value > target
    if relation == "ge":
        return value >= target
    if relation == "lt":
        return value < target
    if relation == "le":
        return value <= target
    if relation == "eq":
        return abs(value - target) <= max(1e-9, abs(target) * 1e-9)
    return True


def _target_unit(question: str, unit_hint: str, plan: StructuredPlan, source_unit: str) -> str:
    return _resolved_target_unit(
        question=question,
        unit_hint=unit_hint,
        plan_target=plan.target_unit,
        source_unit=source_unit,
    )


def _scale(value: float, source_unit: str, target_unit: str) -> float:
    if source_unit == "ratio" and target_unit == "percent":
        return value * 100.0
    return value * conversion_factor(source_unit, target_unit)


def _unit_compatible(source_unit: str, target_unit: str) -> bool:
    if not target_unit or target_unit == "unknown":
        return True
    if source_unit == "ratio":
        return target_unit in {"ratio", "percent"}
    if source_unit in _MONEY_UNITS:
        return target_unit in _MONEY_UNITS
    if source_unit == "year":
        return target_unit == "year"
    if source_unit in {"count", "share"}:
        return target_unit in {"count", "share"}
    return True


def _resolved_target_unit(
    *,
    question: str,
    unit_hint: str,
    plan_target: str,
    source_unit: str,
) -> str:
    target = plan_target if plan_target and plan_target != "unknown" else ""
    if target and _unit_compatible(source_unit, target):
        return target
    from_question = unit_from_hint(question)
    if from_question and _unit_compatible(source_unit, from_question):
        return from_question
    hint = unit_from_hint(unit_hint)
    if hint and _unit_compatible(source_unit, hint):
        return hint
    return target or from_question or source_unit


def _plan_filters(plan: StructuredPlan) -> list[MetricFilter]:
    filters = list(plan.filters)
    if plan.filter_metric and not filters:
        filters.append(
            MetricFilter(
                metric=plan.filter_metric,
                relation=plan.filter_relation,
                value=plan.filter_value,
                value_source="literal" if plan.filter_value is not None else "median",
            )
        )
    return filters


def execute_plan(
    plan: StructuredPlan,
    *,
    question: str,
    unit_hint: str = "",
    store: StatementFactStore | None = None,
) -> dict[str, Any]:
    """Run a structured plan against main-statement facts."""
    if not plan.supported or plan.operation == "unsupported":
        raise StructuredFactError(plan.reason or "plan unsupported")
    if not plan.tickers or not plan.years:
        raise StructuredFactError("plan needs at least one ticker and one year")
    store = store or default_store()
    ctx = _EvalContext(store, plan.doc_type)

    def val(metric: str, ticker: str, year: int) -> tuple[float, str]:
        return _measure_value(ctx, metric, ticker, year, plan)

    source_unit = "unknown"
    answer: float
    selected: dict[str, Any] = {}

    if plan.operation in {"lookup", "ratio"}:
        answer, source_unit = val(plan.answer_expression or plan.answer_metric, plan.tickers[0], plan.years[-1])
    elif plan.operation == "growth":
        metric = plan.answer_metric or plan.selector_metric
        y2 = plan.years[-1]
        y1 = plan.years[-2] if len(plan.years) > 1 else y2 - 1
        v1, _ = val(metric, plan.tickers[0], y1)
        v2, _ = val(metric, plan.tickers[0], y2)
        answer, source_unit = (v2 - v1) / v1, "ratio"
    elif plan.operation == "diff":
        metric = plan.answer_metric or plan.selector_metric
        if len(plan.tickers) >= 2:
            a, source_unit = val(metric, plan.tickers[0], plan.years[-1])
            b, _ = val(metric, plan.tickers[1], plan.years[-1])
        elif len(plan.years) >= 2:
            a, source_unit = val(metric, plan.tickers[0], plan.years[-1])
            b, _ = val(metric, plan.tickers[0], plan.years[0])
        else:
            raise StructuredFactError("diff needs two tickers or two years")
        answer = a - b
    elif plan.operation in {"avg", "median"}:
        metric = plan.answer_metric or plan.selector_metric
        values = [val(metric, plan.tickers[0], year)[0] for year in plan.years]
        source_unit = _measure_value(ctx, metric, plan.tickers[0], plan.years[-1], plan)[1]
        answer = sum(values) / len(values) if plan.operation == "avg" else float(median(values))
    elif plan.operation in {"argmax", "argmin", "conditional_select"}:
        answer, source_unit, selected = _execute_selection(plan, ctx)
    else:
        raise StructuredFactError(f"unsupported operation: {plan.operation}")

    target = _target_unit(question, unit_hint, plan, source_unit)
    scaled = _scale(answer, source_unit, target)
    if plan.round_digits is not None:
        scaled = round(scaled, int(plan.round_digits))
    table_ids = list(dict.fromkeys(f.table_id for f in ctx.facts))
    return {
        "answer": float(scaled),
        "pandas_query": repr(float(scaled)),
        "table_ids": table_ids,
        "evidence": [],
        "diag": {
            "done": True,
            "plan": plan.model_dump(),
            "selected": selected,
            "source_unit": source_unit,
            "target_unit": target,
            "facts": [_fact_diag(f) for f in ctx.facts],
        },
    }


def supported_v1_plan(plan: StructuredPlan, question: str, unit_hint: str = "") -> tuple[bool, str]:
    """The first production slice: selection over years or companies only."""
    if not plan.supported or plan.operation == "unsupported":
        return False, plan.reason or "plan unsupported"
    if plan.operation not in {"argmax", "argmin"}:
        return False, f"operation {plan.operation} outside structured_facts v1"
    if plan.axis == "year" and len(plan.years) < 2:
        return False, "year selection needs at least two years"
    if plan.axis == "ticker" and len(plan.tickers) < 2:
        return False, "ticker selection needs at least two tickers"
    if plan.axis not in {"year", "ticker"}:
        return False, "selection needs a concrete axis"
    if not canonical_measure(plan.selector_metric):
        return False, "selection needs a supported selector_metric"
    if (
        plan.answer_metric != "year"
        and not canonical_measure(plan.answer_expression or plan.answer_metric)
    ):
        return False, "selection needs a supported answer_metric"
    if plan.answer_expression and canonical_metric(plan.answer_metric):
        return False, "answer_expression conflicts with direct answer_metric"
    for flt in _plan_filters(plan):
        if not canonical_measure(flt.metric):
            return False, f"unsupported filter metric: {flt.metric}"
        if not flt.relation:
            return False, f"filter {flt.metric} needs a relation"
        if flt.value is None and flt.value_source != "median":
            return False, f"filter {flt.metric} needs a threshold"
    if plan.year_offset and plan.axis != "year":
        return False, "year_offset only applies to year selections"
    answer_unit = metric_source_unit(plan.answer_expression or plan.answer_metric)
    target = _resolved_target_unit(
        question=question,
        unit_hint=unit_hint,
        plan_target=plan.target_unit,
        source_unit=answer_unit,
    )
    if answer_unit == "ratio" and target and target not in {"ratio", "percent", "unknown"}:
        return False, "ratio answer cannot target a non-ratio unit"
    if answer_unit == "year" and target and target not in {"year", "unknown"}:
        return False, "year answer cannot target a non-year unit"
    if target in _MONEY_UNITS and answer_unit == "ratio":
        return False, "money target cannot be answered by a ratio metric"
    if target in {"ratio", "percent"} and answer_unit in _MONEY_UNITS:
        return False, "ratio target cannot be answered by a money metric"
    return True, ""


def _execute_selection(plan: StructuredPlan, ctx: _EvalContext) -> tuple[float, str, dict[str, Any]]:
    axis = plan.axis or ("ticker" if len(plan.tickers) > 1 else "year")
    selector = plan.selector_metric or plan.answer_metric
    if not selector:
        raise StructuredFactError("selection needs selector_metric")
    elements: list[Any] = list(plan.tickers if axis == "ticker" else plan.years)
    skipped: list[dict[str, str]] = []
    if axis not in {"ticker", "year"}:
        raise StructuredFactError("selection needs axis")

    filter_targets: dict[str, float] = {}
    for flt in _plan_filters(plan):
        if not flt.metric:
            continue
        values: dict[Any, float] = {}
        for element in elements:
            ticker = element if axis == "ticker" else plan.tickers[0]
            year = plan.years[-1] if axis == "ticker" else int(element)
            try:
                fv, _ = _measure_value(ctx, flt.metric, ticker, year, plan)
            except StructuredFactError as exc:
                if plan.missing_policy == "fail":
                    raise
                skipped.append({"element": str(element), "reason": str(exc)})
                continue
            values[element] = fv
        target = flt.value
        if flt.value_source == "median":
            finite_values = [v for v in values.values() if _finite(v)]
            if not finite_values:
                raise StructuredFactError(f"filter {flt.metric} has no live values")
            target = float(median(finite_values))
        if target is None:
            raise StructuredFactError(f"filter {flt.metric} needs a threshold")
        filter_targets[flt.metric] = float(target)
        filtered: list[Any] = []
        for element in elements:
            fv = values.get(element)
            if _finite(fv) and _passes(float(fv), flt.relation or "lt", float(target)):
                filtered.append(element)
        elements = filtered

    candidates: list[tuple[Any, float]] = []
    if axis == "ticker":
        for ticker in elements:
            try:
                score, _ = _measure_value(ctx, selector, ticker, plan.years[-1], plan)
            except StructuredFactError as exc:
                if plan.missing_policy == "fail":
                    raise
                skipped.append({"element": ticker, "reason": str(exc)})
                continue
            candidates.append((ticker, score))
    else:
        for year in elements:
            try:
                score, _ = _measure_value(ctx, selector, plan.tickers[0], int(year), plan)
            except StructuredFactError as exc:
                if plan.missing_policy == "fail":
                    raise
                skipped.append({"element": str(year), "reason": str(exc)})
                continue
            candidates.append((year, score))

    if not candidates:
        raise StructuredFactError("selection has no live candidates")
    order = plan.selector_order or ("min" if plan.operation == "argmin" else "max")
    reverse = order != "min"
    winner, score = sorted(candidates, key=lambda item: item[1], reverse=reverse)[0]
    if plan.answer_metric == "year":
        return float(winner), "year", {
            "axis": axis, "winner": winner, "selector_value": score,
            "skipped": skipped, "filter_targets": filter_targets,
        }
    ticker = winner if axis == "ticker" else plan.tickers[0]
    year = plan.years[-1] if axis == "ticker" else int(winner) + int(plan.year_offset)
    selected = {
        "axis": axis,
        "winner": winner,
        "answer_year": year,
        "selector_value": score,
        "skipped": skipped,
        "filter_targets": filter_targets,
    }
    answer, unit = _measure_value(
        ctx, plan.answer_expression or plan.answer_metric, ticker, year, plan, selected
    )
    return answer, unit, {
        **selected,
    }


def _fact_diag(fact: Fact) -> dict[str, Any]:
    row = fact.row
    return {
        "table_id": fact.table_id,
        "ticker": row.get("ticker"),
        "year": int(row.get("year")),
        "doc_type": row.get("doc_type"),
        "statement_type": row.get("statement_type"),
        "ma_so": row.get("ma_so"),
        "label": row.get("label"),
        "period": row.get("period"),
        "value": fact.value,
        "fact_source": row.get("fact_source"),
        "source_unit": row.get("source_unit"),
        "source_unit_from": row.get("source_unit_from"),
    }


PLAN_SYSTEM = """\
Bạn điền schema StructuredPlannerOutput cho bộ executor fact tài chính.
Chỉ trả về schema. Không viết code.

Fact table chỉ bao phủ balance_sheet, income_statement, cash_flow có mã số VAS.
Nếu câu hỏi cần thuyết minh, entity_info, equity_change, ngân hàng/CTCK đặc thù hoặc
không biểu diễn được bằng schema thì đặt supported=false.

Metric/expression/unit hợp lệ đã được ràng buộc trong schema enum.
Tickers, years, doc_type là scope đã resolve sẵn.
"""


async def aplan_structured(
    *,
    question: str,
    tickers: list[str],
    years: list[int],
    doc_type: str,
    metric: str = "",
    operation: str = "",
    unit_hint: str = "",
    planner_thinking: bool = False,
) -> StructuredPlan:
    """Ask the LLM for a bounded plan.

    A bad or missing plan must fall back to raw-grid codegen, not to regex-derived
    solve semantics here. This function only fills retrieval-owned scope fields
    if the model omitted them.
    """
    try:
        user = (
            f"Câu hỏi: {question}\n"
            f"Tickers đã resolve: {tickers}\n"
            f"Years đã resolve: {years}\n"
            f"doc_type: {doc_type}\n"
            f"understand.metric: {metric}\n"
            f"understand.operation: {operation}\n"
            f"unit_hint: {unit_hint}\n"
        )
        result = await get_chat_model(
            thinking=planner_thinking,
            max_tokens=8192 if planner_thinking else 768,
        ).with_structured_output(
            StructuredPlannerOutput
        ).ainvoke([
            SystemMessage(content=PLAN_SYSTEM),
            HumanMessage(content=user),
        ])
        planner_output = (
            result
            if isinstance(result, StructuredPlannerOutput)
            else StructuredPlannerOutput.model_validate(result)
        )
        plan = planner_output.to_structured_plan()
    except Exception as exc:
        return heuristic_plan(
            question=question, tickers=tickers, years=years, doc_type=doc_type,
            metric=metric, operation=operation, unit_hint=unit_hint,
            reason=f"structured planner unavailable: {type(exc).__name__}: {exc}",
        )
    if not plan.tickers:
        plan.tickers = [str(t).upper().strip() for t in tickers if str(t).strip()]
    if not plan.years:
        plan.years = sorted({int(y) for y in years if y})
    if plan.doc_type == "unknown":
        plan.doc_type = doc_type if doc_type in {"consolidated", "separate"} else "unknown"
    resolved_unit = unit_from_hint(unit_hint) or unit_from_hint(question)
    if resolved_unit:
        plan.target_unit = resolved_unit
    return normalize_plan(plan)


def normalize_plan(plan: StructuredPlan) -> StructuredPlan:
    """Deterministic normalization that does not infer solve semantics."""
    if plan.axis == "year":
        plan.missing_policy = "fail"
    return plan


def heuristic_plan(
    *,
    question: str,
    tickers: list[str],
    years: list[int],
    doc_type: str,
    metric: str = "",
    operation: str = "",
    unit_hint: str = "",
    reason: str = "structured planner unavailable",
) -> StructuredPlan:
    """No semantic fallback: planner failures should route to raw-table codegen."""
    _ = question, operation, unit_hint
    return normalize_plan(StructuredPlan(
        supported=False,
        operation="unsupported",
        axis="ticker" if len(tickers) > 1 else ("year" if len(years) > 1 else ""),
        tickers=tickers,
        years=years,
        doc_type=doc_type if doc_type in {"consolidated", "separate"} else "unknown",
        answer_metric=canonical_metric(metric),
        reason=reason,
    ))


async def asolve_structured_facts(
    state: dict[str, Any],
    *,
    planner_thinking: bool = False,
) -> dict[str, Any]:
    """Plan and execute a structured fact answer for one graph state."""
    plan = await aplan_structured(
        question=state["question"],
        tickers=list(state.get("tickers") or []),
        years=list(state.get("years") or []),
        doc_type=state.get("doc_type") or "unknown",
        metric=state.get("metric") or "",
        operation=state.get("operation") or "",
        unit_hint=state.get("unit_hint") or "",
        planner_thinking=planner_thinking,
    )
    ok, reason = supported_v1_plan(
        plan, state["question"], state.get("unit_hint") or "",
    )
    if not ok:
        raise StructuredFactError(reason)
    return execute_plan(
        plan,
        question=state["question"],
        unit_hint=state.get("unit_hint") or "",
    )


__all__ = [
    "METRIC_KEYS",
    "PRIMITIVES",
    "EXPRESSION_KEYS",
    "MetricFilter",
    "PlannerMetricFilter",
    "StatementFactStore",
    "StructuredFactError",
    "StructuredPlannerOutput",
    "StructuredSelectionPlan",
    "StructuredPlan",
    "UnsupportedStructuredPlan",
    "aplan_structured",
    "asolve_structured_facts",
    "canonical_metric",
    "canonical_measure",
    "execute_plan",
    "heuristic_plan",
    "metric_source_unit",
    "metrics_in_text",
    "supported_v1_plan",
]
