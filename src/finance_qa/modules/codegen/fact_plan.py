"""Typed fact-table planning and deterministic execution.

`CanonicalPlan` is intentionally small and stable. This module handles richer
question shapes over normalized ticker/year facts: median-relative filters,
aggregates, prior-year growth metrics, scenario ICR, and inventory-days cash
release. The model fills a Pydantic plan; Python owns all calculations.
"""
from __future__ import annotations

import math
from typing import Any
from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, model_validator

from finance_qa.core.llm import get_chat_model
from finance_qa.modules.codegen.facts import FactRow, materialize_fact_table
from finance_qa.modules.tools.metrics import (
    CanonicalData,
    METRICS,
    convert_unit,
    full_metric_catalog,
    metric_ids,
)


FactMetricId = Literal[*metric_ids()]
FactValueId = Literal[*metric_ids(), "scenario_icr", "inventory_release_to_median"]
FactFilterOp = Literal[">", ">=", "<", "<=", "==", "below_median", "above_median"]
FactDirection = Literal["max", "min"]
FactAggregate = Literal["mean", "median", "sum", "min", "max"]
FactScenarioKind = Literal["none", "ebit_proxy_multiplier"]

_PERCENT_THRESHOLD_METRICS = {
    "gross_margin",
    "operating_margin",
    "net_margin",
    "inventory_to_assets",
    "debt_ratio",
    "cash_ratio",
    "revenue_growth",
    "operating_profit_growth",
}


class FactUniverse(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)


class FactFilter(BaseModel):
    metric: FactMetricId
    op: FactFilterOp
    value: float | None = None


class FactSelect(BaseModel):
    metric: FactValueId
    direction: FactDirection
    offset_years: int = Field(default=0, description="1 for next year, -1 for previous year.")


class FactScenario(BaseModel):
    kind: FactScenarioKind = "none"
    multiplier: float = Field(default=1.0, description="0.85 means EBIT proxy decreases 15%.")


class FactAnswer(BaseModel):
    metric: FactValueId
    unit: str = ""
    aggregate: FactAggregate | None = None


class FactPlan(BaseModel):
    """Structured plan over a normalized ticker/year fact table."""

    unsupported: bool = False
    median_filter_mentioned: bool = False
    universe: FactUniverse = Field(default_factory=FactUniverse)
    filters: list[FactFilter] = Field(default_factory=list)
    select: FactSelect | None = None
    scenario: FactScenario = Field(default_factory=FactScenario)
    answer: FactAnswer | None = None

    @model_validator(mode="after")
    def validate_consistency(self):
        if self.unsupported:
            return self
        if self.answer is None:
            raise ValueError("supported fact plans must include answer")
        for filt in self.filters:
            if filt.op in {"below_median", "above_median"}:
                self.median_filter_mentioned = True
            elif filt.value is None:
                raise ValueError(f"filter op {filt.op!r} requires a numeric value")
        uses_scenario = (
            self.answer.metric == "scenario_icr"
            or (self.select is not None and self.select.metric == "scenario_icr")
        )
        if self.select is not None and abs(self.select.offset_years) > 1:
            raise ValueError("offset_years only supports -1, 0, or 1")
        if uses_scenario and self.scenario.kind != "ebit_proxy_multiplier":
            raise ValueError("scenario_icr requires scenario.kind='ebit_proxy_multiplier'")
        if self.answer.metric == "inventory_release_to_median" and not any(
            filt.metric == "inventory_days" and filt.op in {"above_median", "below_median"}
            for filt in self.filters
        ):
            raise ValueError("inventory_release_to_median requires an inventory_days median filter")
        return self


def _fact_plan_prompt(question: str) -> str:
    return f"""\
Câu hỏi: {question}

Điền đúng FactPlan ngắn gọn để Python execute trên bảng fact ticker/year.
Chỉ lập plan, không giải thích, không tự tính số.

Metric catalog:
{full_metric_catalog()}

Special values:
- scenario_icr: ICR theo kịch bản EBIT proxy đổi, ví dụ giảm 15% => scenario.kind="ebit_proxy_multiplier", multiplier=0.85.
- inventory_release_to_median: tiền giải phóng nếu đưa DOH về median; cần filter inventory_days above_median.

Rules:
- Không thêm filter/metric không được câu hỏi nhắc tới.
- Ngưỡng phần trăm phải là số thập phân: 3% -> 0.03, 14.37% -> 0.1437.
- D/E = de_ratio.
- Khả năng thanh toán lãi vay / EBIT gấp chi phí lãi vay = icr.
- EBIT proxy = profit_before_tax + abs(interest_expense).
- "lợi nhuận trước lãi vay và thuế gấp bao nhiêu lần chi phí lãi vay" trả answer.metric=icr,
  không trả profit_before_tax và không thêm filter interest_expense > 0.
- Thanh toán hiện hành = current_ratio; thanh toán nhanh = quick_ratio.
- CFO trên LNST = cfo_to_net_profit; CFO trên doanh thu thuần = cash_ratio.
- Dòng tiền hoạt động trên nợ ngắn hạn = cfo_to_short_term_debt.
- Biên lợi nhuận ròng = net_margin; biên lợi nhuận hoạt động = operating_margin.
- Tăng doanh thu thuần so với kỳ so sánh = revenue_growth.
- Lợi nhuận thuần từ HĐKD dương ở cả hai kỳ = filters operating_profit > 0 và prev_operating_profit > 0.
- Đòn bẩy kinh doanh = operating_leverage.
- Số ngày tồn kho / DOH = inventory_days.
- Vòng quay tài sản cố định = fixed_asset_turnover; bình quân TSCĐ = avg_fixed_assets.
- "trung vị/median" dùng below_median hoặc above_median và median_filter_mentioned=true.
- "bình quân/trung bình của các doanh nghiệp/năm sau filter" dùng answer.aggregate="mean", không chọn min/max một row.
- Với "Y của doanh nghiệp/năm có X cao nhất/thấp nhất": select.metric=X, answer.metric=Y.
- Với "năm sau/năm kế tiếp/năm tiếp theo năm có X": select.offset_years=1.
- Với "năm trước năm có X": select.offset_years=-1.
- Với "thấp nhất/cao nhất theo kịch bản": select.metric=scenario_icr, answer.metric=scenario_icr.
- Nếu câu hỏi hỏi tiền giải phóng do đưa DOH về median: filter inventory_days above_median,
  select.metric=inventory_days direction=max, answer.metric=inventory_release_to_median.
- Nếu metric không có trong catalog/special values thì đặt unsupported=true.

Ví dụ:
- "hệ số thanh toán nhanh của doanh nghiệp có CFO/LNST cao nhất"
  -> select cfo_to_net_profit max, answer quick_ratio.
- "biên lợi nhuận ròng bình quân của nhóm có inventory/asset cao hơn trung vị"
  -> filter inventory_to_assets above_median, answer net_margin aggregate mean.
- "ROE của năm có CFO/doanh thu cao nhất trong các năm có gross margin thấp hơn median"
  -> filter gross_margin below_median, select cash_ratio max, answer roe.
- "doanh nghiệp có vòng quay TSCĐ thấp hơn median, bình quân TSCĐ lớn nhất tạo doanh thu bao nhiêu lần"
  -> filter fixed_asset_turnover below_median, select avg_fixed_assets max,
     answer fixed_asset_turnover.
- "năm có D/E cao nhất, EBIT gấp chi phí lãi vay bao nhiêu lần"
  -> select de_ratio max, answer icr.
- "dòng tiền hoạt động trên nợ ngắn hạn vào năm sau năm có thanh toán nhanh thấp nhất"
  -> select quick_ratio min offset_years=1, answer cfo_to_short_term_debt.
"""


def infer_fact_plan(question: str) -> FactPlan | None:
    """Infer a typed fact-table plan without executing it."""
    prompt = _fact_plan_prompt(question)
    for method in ("json_schema", "function_calling"):
        try:
            plan_obj = get_chat_model(thinking=False, max_tokens=2048).with_structured_output(
                FactPlan,
                method=method,
            ).invoke([HumanMessage(prompt)])
        except Exception:
            continue
        if isinstance(plan_obj, FactPlan):
            return plan_obj
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _aggregate(values: list[float], op: str) -> float | None:
    if not values:
        return None
    if op == "mean":
        return sum(values) / len(values)
    if op == "median":
        return _median(values)
    if op == "sum":
        return sum(values)
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    return None


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == "==":
        return value == threshold
    return False


def _row_value(
    row: FactRow,
    metric_id: str,
    *,
    scenario: FactScenario,
    thresholds: dict[str, float],
) -> float | None:
    if metric_id == "scenario_icr":
        pbt = row.get("profit_before_tax")
        interest = row.get("interest_expense")
        if pbt is None or interest is None or not interest:
            return None
        value = scenario.multiplier * (pbt + abs(interest)) / abs(interest)
    elif metric_id == "inventory_release_to_median":
        inventory_days = row.get("inventory_days")
        cogs = row.get("cogs")
        median_days = thresholds.get("inventory_days")
        if inventory_days is None or cogs is None or median_days is None:
            return None
        value = max(0.0, inventory_days - median_days) * abs(cogs) / 365.0
    else:
        value = row.get(metric_id)
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _apply_filters(
    rows: list[FactRow],
    filters: list[FactFilter],
    scenario: FactScenario,
) -> tuple[list[FactRow], dict[str, float]] | None:
    kept = list(rows)
    thresholds: dict[str, float] = {}
    for filt in filters:
        if filt.op in {"below_median", "above_median"}:
            values = [
                value
                for row in kept
                if (value := _row_value(row, filt.metric, scenario=scenario, thresholds=thresholds)) is not None
            ]
            threshold = _median(values)
            if threshold is None:
                return None
            thresholds[filt.metric] = threshold
            op = "<" if filt.op == "below_median" else ">"
        else:
            threshold = filt.value
            if threshold is None:
                return None
            if filt.metric in _PERCENT_THRESHOLD_METRICS and 1.0 < abs(float(threshold)) <= 100.0:
                threshold = float(threshold) / 100.0
            op = filt.op
        next_rows = [
            row
            for row in kept
            if (
                value := _row_value(row, filt.metric, scenario=scenario, thresholds=thresholds)
            ) is not None
            and _compare(value, op, float(threshold))
        ]
        kept = next_rows
    return kept, thresholds


def _pick_row(
    rows: list[FactRow],
    select: FactSelect,
    scenario: FactScenario,
    thresholds: dict[str, float],
) -> FactRow | None:
    scored = [
        (value, row)
        for row in rows
        if (value := _row_value(row, select.metric, scenario=scenario, thresholds=thresholds)) is not None
    ]
    if not scored:
        return None
    return (max if select.direction == "max" else min)(scored, key=lambda item: item[0])[1]


def execute_fact_plan(
    data: CanonicalData,
    plan: FactPlan | dict,
    *,
    default_tickers: list[str] | None = None,
    default_years: list[int] | None = None,
    unit_hint: str | None = None,
    resolved: dict[str, Any] | None = None,
) -> tuple[float, str] | None:
    """Execute a typed fact-table plan deterministically.

    On success, `resolved` (when given) records the row and unit the answer was
    read from -- only for single-row answers, since an aggregate over many rows
    has no single source cell.
    """
    if isinstance(plan, dict):
        try:
            plan = FactPlan.model_validate(plan)
        except Exception:
            return None
    if not isinstance(plan, FactPlan) or plan.unsupported or plan.answer is None:
        return None

    tickers = default_tickers or plan.universe.tickers
    years = default_years or plan.universe.years
    try:
        years = [int(year) for year in years]
    except (TypeError, ValueError):
        return None

    table = materialize_fact_table(data, tickers=tickers, years=years, metrics=metric_ids())
    if not table.rows:
        return None

    filtered = _apply_filters(table.rows, plan.filters, plan.scenario)
    if filtered is None:
        return None
    rows, thresholds = filtered
    if not rows:
        return None

    answer = plan.answer
    aggregate_wins = (
        answer.aggregate is not None
        and (plan.select is None or plan.select.metric == answer.metric)
    )
    if plan.select is not None and not aggregate_wins:
        selected = _pick_row(rows, plan.select, plan.scenario, thresholds)
        if selected is None:
            return None
        if plan.select.offset_years:
            shifted_year = selected.year + int(plan.select.offset_years)
            shifted = materialize_fact_table(
                data,
                tickers=[selected.ticker],
                years=[shifted_year],
                metrics=metric_ids(),
            ).rows
            if not shifted:
                return None
            selected = shifted[0]
        value = _row_value(selected, answer.metric, scenario=plan.scenario, thresholds=thresholds)
    elif answer.aggregate:
        values = [
            value
            for row in rows
            if (value := _row_value(row, answer.metric, scenario=plan.scenario, thresholds=thresholds)) is not None
        ]
        value = _aggregate(values, answer.aggregate)
        selected = None
    elif len(rows) == 1:
        selected = rows[0]
        value = _row_value(selected, answer.metric, scenario=plan.scenario, thresholds=thresholds)
    else:
        return None

    if value is None:
        return None
    unit_metric = answer.metric
    if answer.metric == "inventory_release_to_median":
        unit_metric = "net_revenue"
    elif answer.metric == "scenario_icr":
        unit_metric = "icr"
    unit = unit_hint or answer.unit
    converted = convert_unit(value, unit_metric if unit_metric in METRICS else "", unit)
    if resolved is not None and selected is not None:
        resolved.update(
            ticker=selected.ticker, year=selected.year, metric=answer.metric, unit=unit
        )
    query = "fact_plan("
    if selected is not None:
        query += f"ticker={selected.ticker},year={selected.year},"
    query += f"answer={answer.metric}"
    if answer.aggregate and aggregate_wins:
        query += f".{answer.aggregate}"
    if plan.select:
        query += f",select={plan.select.metric}.{plan.select.direction}"
        if plan.select.offset_years:
            query += f",offset_years={plan.select.offset_years}"
    if plan.filters:
        query += f",filters={len(plan.filters)}"
    if plan.scenario.kind != "none":
        query += f",scenario={plan.scenario.kind}:{plan.scenario.multiplier:g}"
    query += ")"
    return converted, query


def plan_and_execute_fact_plan(
    question: str,
    data: CanonicalData,
    *,
    tickers: list[str] | None = None,
    years: list[int] | None = None,
    unit_hint: str | None = None,
    resolved: dict[str, Any] | None = None,
) -> tuple[float, str] | None:
    plan = infer_fact_plan(question)
    if plan is None:
        return None
    return execute_fact_plan(
        data,
        plan,
        default_tickers=tickers or [],
        default_years=years or [],
        unit_hint=unit_hint,
        resolved=resolved,
    )
