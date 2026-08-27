"""Plan schemas: the executor-facing StructuredPlan and the narrower LLM-facing schema."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finance_qa.modules.solve.facts.metrics import (
    EXPRESSION_KEYS,
    EXPRESSION_SCHEMA_DESCRIPTION,
    METRIC_KEYS,
    METRIC_SCHEMA_DESCRIPTION,
    canonical_measure,
)

Operation = Literal[
    "lookup", "ratio", "growth", "diff", "avg", "median",
    "argmax", "argmin", "conditional_select", "filter_aggregate", "unsupported",
]
# `filter_aggregate` reuses the candidate filtering that argmax/argmin already
# perform, then aggregates the survivors instead of ranking them. `share` is the
# survivors' total over the whole candidate set's total ("ty trong ... cua ca
# nhom"); the rest aggregate the survivors alone.
Aggregation = Literal["", "mean", "median", "sum", "count", "share"]
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

PlannerMetric = Literal[*METRIC_KEYS]
PlannerExpression = Literal[*EXPRESSION_KEYS]
PlannerMeasure = Literal["", *METRIC_KEYS, *EXPRESSION_KEYS]
PlannerMeasureNoEmpty = Literal[*METRIC_KEYS, *EXPRESSION_KEYS]
PlannerFilterMeasure = Literal[*METRIC_KEYS, *EXPRESSION_KEYS]
PlannerAnswerMetricNoEmpty = Literal["year", *METRIC_KEYS]
PlannerAnswerMetric = Literal["", "year", *METRIC_KEYS]
PlannerAnswerExpression = Literal["", *EXPRESSION_KEYS]


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
    aggregation: Aggregation = Field(default="")
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


__all__ = [
    "MetricFilter",
    "PlannerAnswer",
    "PlannerExpressionAnswer",
    "PlannerMetricAnswer",
    "PlannerMetricFilter",
    "PlannerPlan",
    "StructuredPlan",
    "StructuredPlannerOutput",
    "StructuredSelectionPlan",
    "UnsupportedStructuredPlan",
]
