"""Deterministic executor for a validated StructuredPlan."""
from __future__ import annotations

import re
from statistics import median
from typing import Any

from finance_qa.modules.data.table_store import submission_csv_name
from finance_qa.modules.solve.common.units import conversion_factor, unit_from_hint
from finance_qa.modules.solve.facts.cellexpr import Num, cell_expression
from finance_qa.modules.solve.facts.metrics import (
    PRIMITIVES,
    _MONEY_UNITS,
    canonical_measure,
    canonical_metric,
    metric_source_unit,
)
from finance_qa.modules.solve.facts.schema import MetricFilter, StructuredPlan
from finance_qa.modules.solve.facts.store import (
    Fact,
    StatementFactStore,
    StructuredFactError,
    _finite,
    default_store,
)


class _EvalContext:
    def __init__(self, store: StatementFactStore, doc_type: str):
        self.store = store
        self.doc_type = doc_type
        self.facts: list[Fact] = []
        # table_id -> dfN, đánh số theo thứ tự gặp đầu tiên, giống cách codegen
        # đặt tên khung dữ liệu cho các bảng nó được đưa.
        self.names: dict[str, str] = {}

    def variable(self, table_id: str) -> str:
        if table_id not in self.names:
            self.names[table_id] = f"df{len(self.names)}"
        return self.names[table_id]

    def primitive(self, key: str, ticker: str, year: int, period_kind: str = "end") -> Num:
        metric = PRIMITIVES[key]
        fact = self.store.value(
            ticker=ticker, year=year, doc_type=self.doc_type,
            metric=metric, period_kind=period_kind,
        )
        self.facts.append(fact)
        return Num(fact.value, cell_expression(fact, self.variable(fact.table_id)))


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
    # Không bọc `float()`: nó cắt mất biểu thức mà `Num` đang mang theo.
    return num / den


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
        answer = sum(values) / len(values) if plan.operation == "avg" else median(values)
    elif plan.operation in {"argmax", "argmin", "conditional_select"}:
        answer, source_unit, selected = _execute_selection(plan, ctx)
    elif plan.operation == "filter_aggregate":
        answer, source_unit, selected = _execute_aggregate(plan, ctx)
    else:
        raise StructuredFactError(f"unsupported operation: {plan.operation}")

    target = _target_unit(question, unit_hint, plan, source_unit)
    scaled = _scale(answer, source_unit, target)
    if plan.round_digits is not None:
        scaled = round(scaled, int(plan.round_digits))
    table_ids = list(dict.fromkeys(f.table_id for f in ctx.facts))
    query, evidence = _query_and_evidence(scaled, ctx)
    return {
        "answer": float(scaled),
        "pandas_query": query,
        "table_ids": table_ids,
        "evidence": evidence,
        "diag": {
            "done": True,
            "plan": plan.model_dump(),
            "selected": selected,
            "source_unit": source_unit,
            "target_unit": target,
            "facts": [_fact_diag(f) for f in ctx.facts],
        },
    }


_DF_VAR = re.compile(r"\bdf\d+\b")


def _query_and_evidence(scaled: Any, ctx: _EvalContext) -> tuple[str, list[dict]]:
    """Biểu thức đọc ô cùng evidence của nó, hoặc `("", [])` nếu không dựng được.

    Fact nào trong phép tính không định vị được ô thì đáp án chỉ còn cách trình
    bày bằng một hằng số, mà luật (`final_submission.md`) chấm 0 cho câu gán
    cứng. Hàm này báo "không có biểu thức" bằng chuỗi rỗng; `_run_fact_solver`
    là nơi quyết định nhường câu đó cho solver sau.
    """
    expr = scaled.expr if isinstance(scaled, Num) else None
    if not expr:
        return "", []
    read = set(_DF_VAR.findall(expr))
    evidence = [
        {"variable": var, "csv_path": f"data/{submission_csv_name(table_id)}"}
        for table_id, var in ctx.names.items()
        if var in read
    ]
    return expr, evidence


def _supported_filters(plan: StructuredPlan) -> tuple[bool, str]:
    for flt in _plan_filters(plan):
        if not canonical_measure(flt.metric):
            return False, f"unsupported filter metric: {flt.metric}"
        if not flt.relation:
            return False, f"filter {flt.metric} needs a relation"
        if flt.value is None and flt.value_source != "median":
            return False, f"filter {flt.metric} needs a threshold"
    return True, ""


def _supported_answer_unit(
    plan: StructuredPlan, question: str, unit_hint: str, answer_unit: str,
) -> tuple[bool, str]:
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


def _supported_filter_aggregate(
    plan: StructuredPlan, question: str, unit_hint: str,
) -> tuple[bool, str]:
    """Validation for the filter -> aggregate slice.

    Deliberately narrower than the shape the executor can run: only the ticker
    axis over a single year, which is the slice measured as reachable without a
    year-pair (delta) measure. Widening this is a separate, separately measured
    change.
    """
    if plan.aggregation not in {"mean", "median", "sum", "count", "share"}:
        return False, f"aggregate needs a supported aggregation, got {plan.aggregation!r}"
    if plan.axis != "ticker":
        return False, "filter_aggregate v1 covers the ticker axis only"
    if len(plan.tickers) < 2:
        return False, "aggregate needs at least two candidate tickers"
    if len(plan.years) != 1:
        return False, "filter_aggregate v1 covers a single-year scope only"
    if not _plan_filters(plan):
        return False, "aggregate needs at least one filter"
    if plan.year_offset:
        return False, "year_offset does not apply to filter_aggregate"
    if plan.selector_metric or plan.selector_order:
        return False, "filter_aggregate does not rank candidates"
    ok, reason = _supported_filters(plan)
    if not ok:
        return ok, reason
    if plan.aggregation == "count":
        if plan.answer_metric or plan.answer_expression:
            return False, "count aggregate must not name an answer metric"
        return True, ""
    if not canonical_measure(plan.answer_expression or plan.answer_metric):
        return False, "aggregate needs a supported answer_metric"
    if plan.answer_expression and canonical_metric(plan.answer_metric):
        return False, "answer_expression conflicts with direct answer_metric"
    # A share is dimensionless whatever the underlying metric is.
    answer_unit = (
        "ratio" if plan.aggregation == "share"
        else metric_source_unit(plan.answer_expression or plan.answer_metric)
    )
    return _supported_answer_unit(plan, question, unit_hint, answer_unit)


def supported_v1_plan(plan: StructuredPlan, question: str, unit_hint: str = "") -> tuple[bool, str]:
    """The first production slice: selection over years or companies only."""
    if not plan.supported or plan.operation == "unsupported":
        return False, plan.reason or "plan unsupported"
    if plan.operation == "filter_aggregate":
        # Separate branch on purpose: the argmax/argmin path below is unchanged,
        # so admitting aggregates cannot alter any plan that already validated.
        return _supported_filter_aggregate(plan, question, unit_hint)
    if plan.operation not in {"argmax", "argmin"}:
        return False, f"operation {plan.operation} outside structured_facts v1"
    if plan.aggregation:
        return False, "aggregation only applies to filter_aggregate"
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
    ok, reason = _supported_filters(plan)
    if not ok:
        return ok, reason
    if plan.year_offset and plan.axis != "year":
        return False, "year_offset only applies to year selections"
    answer_unit = metric_source_unit(plan.answer_expression or plan.answer_metric)
    return _supported_answer_unit(plan, question, unit_hint, answer_unit)


def _resolve_axis(plan: StructuredPlan) -> str:
    axis = plan.axis or ("ticker" if len(plan.tickers) > 1 else "year")
    if axis not in {"ticker", "year"}:
        raise StructuredFactError("selection needs axis")
    return axis


def _survivors(
    plan: StructuredPlan,
    ctx: _EvalContext,
    axis: str,
    skipped: list[dict[str, str]],
) -> tuple[list[Any], dict[str, float]]:
    """Shrink the candidate set by every filter, returning the survivors.

    Shared by `_execute_selection` (which then ranks them) and
    `_execute_aggregate` (which then aggregates them). Extracted verbatim from
    `_execute_selection`; a filter's threshold may be a literal or the
    candidate-set median, and `missing_policy="skip"` drops candidates whose
    filter metric has no fact coverage instead of failing the whole plan.
    """
    elements: list[Any] = list(plan.tickers if axis == "ticker" else plan.years)
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
    return elements, filter_targets


def _element_values(
    plan: StructuredPlan,
    ctx: _EvalContext,
    axis: str,
    metric: str,
    elements: list[Any],
    skipped: list[dict[str, str]],
) -> tuple[list[tuple[Any, float]], str]:
    """Evaluate `metric` once per candidate, honouring `missing_policy`."""
    out: list[tuple[Any, float]] = []
    unit = "unknown"
    for element in elements:
        ticker = element if axis == "ticker" else plan.tickers[0]
        year = plan.years[-1] if axis == "ticker" else int(element)
        try:
            value, unit_here = _measure_value(ctx, metric, ticker, year, plan)
        except StructuredFactError as exc:
            if plan.missing_policy == "fail":
                raise
            skipped.append({"element": str(element), "reason": str(exc)})
            continue
        if not _finite(value):
            if plan.missing_policy == "fail":
                raise StructuredFactError(f"{metric} is not finite for {ticker} {year}")
            skipped.append({"element": str(element), "reason": f"{metric} not finite"})
            continue
        unit = unit_here
        out.append((element, value))
    return out, unit


def _execute_aggregate(plan: StructuredPlan, ctx: _EvalContext) -> tuple[float, str, dict[str, Any]]:
    """Filter the candidate set, then aggregate the survivors."""
    axis = _resolve_axis(plan)
    skipped: list[dict[str, str]] = []
    survivors, filter_targets = _survivors(plan, ctx, axis, skipped)
    selected: dict[str, Any] = {
        "axis": axis,
        "survivors": list(survivors),
        "skipped": skipped,
        "filter_targets": filter_targets,
        "aggregation": plan.aggregation,
    }

    if plan.aggregation == "count":
        # A count is the size of the surviving set; no answer metric is read, so
        # an empty survivor set is a legitimate answer of zero.
        return float(len(survivors)), "count", selected

    if not survivors:
        raise StructuredFactError("aggregate has no surviving candidates")
    metric = plan.answer_expression or plan.answer_metric
    if not metric:
        raise StructuredFactError("aggregate needs answer_metric")

    pairs, unit = _element_values(plan, ctx, axis, metric, survivors, skipped)
    if not pairs:
        raise StructuredFactError(f"aggregate has no live {metric} values")
    values = [value for _, value in pairs]
    selected["values"] = {str(element): value for element, value in pairs}

    if plan.aggregation == "share":
        # Share of the *whole* candidate set, so the denominator is rebuilt from
        # every element, not just the survivors.
        all_elements = list(plan.tickers if axis == "ticker" else plan.years)
        whole, _ = _element_values(plan, ctx, axis, metric, all_elements, skipped)
        total = sum(value for _, value in whole)
        if not total:
            raise StructuredFactError(f"share denominator for {metric} is zero")
        selected["denominator"] = total
        return _divide(sum(values), total), "ratio", selected
    if plan.aggregation == "mean":
        return sum(values) / len(values), unit, selected
    if plan.aggregation == "median":
        return median(values), unit, selected
    if plan.aggregation == "sum":
        return sum(values), unit, selected
    raise StructuredFactError(f"unsupported aggregation: {plan.aggregation}")


def _execute_selection(plan: StructuredPlan, ctx: _EvalContext) -> tuple[float, str, dict[str, Any]]:
    axis = _resolve_axis(plan)
    selector = plan.selector_metric or plan.answer_metric
    if not selector:
        raise StructuredFactError("selection needs selector_metric")
    skipped: list[dict[str, str]] = []
    elements, filter_targets = _survivors(plan, ctx, axis, skipped)

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


__all__ = [
    "execute_plan",
    "supported_v1_plan",
]
