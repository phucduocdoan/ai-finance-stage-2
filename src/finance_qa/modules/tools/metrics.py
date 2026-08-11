"""Deterministic execution over canonical financial statement metrics.

The model may infer a structured plan from Vietnamese text, but arithmetic and
data access stay here. Returning ``None`` means "unsupported or insufficient
data", so callers can fall back to a more general solver instead of guessing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


CanonicalData = dict[str, dict[str, dict[str, float]]]


def _safe_div(a: float, b: float) -> float | None:
    if not b or math.isnan(b) or math.isnan(a):
        return None
    result = a / b
    return None if math.isinf(result) else result


@dataclass(frozen=True)
class TracedValue:
    """A float that carries the pandas expression it was computed from.

    Metric formulas are plain arithmetic over a {metric: float} mapping, so
    running them over TracedValue instead of float yields the expression for
    free -- there is no second copy of the formula table to keep in sync.
    """

    value: float
    expr: str

    def __float__(self) -> float:
        return self.value

    def __bool__(self) -> bool:
        return bool(self.value)

    def _combine(self, other: Any, symbol: str, flip: bool) -> "TracedValue":
        if isinstance(other, TracedValue):
            other_value, other_expr = other.value, other.expr
        else:
            try:
                other_value = float(other)
            except (TypeError, ValueError):
                return NotImplemented
            other_expr = repr(other_value)
        left, right = (other_expr, self.expr) if flip else (self.expr, other_expr)
        lhs, rhs = (other_value, self.value) if flip else (self.value, other_value)
        if symbol == "+":
            value = lhs + rhs
        elif symbol == "-":
            value = lhs - rhs
        elif symbol == "*":
            value = lhs * rhs
        else:
            if not rhs:
                raise ZeroDivisionError(right)
            value = lhs / rhs
        return TracedValue(value, f"({left} {symbol} {right})")

    def __add__(self, other): return self._combine(other, "+", flip=False)
    def __radd__(self, other): return self._combine(other, "+", flip=True)
    def __sub__(self, other): return self._combine(other, "-", flip=False)
    def __rsub__(self, other): return self._combine(other, "-", flip=True)
    def __mul__(self, other): return self._combine(other, "*", flip=False)
    def __rmul__(self, other): return self._combine(other, "*", flip=True)
    def __truediv__(self, other): return self._combine(other, "/", flip=False)
    def __rtruediv__(self, other): return self._combine(other, "/", flip=True)

    def __abs__(self) -> "TracedValue":
        # Fold the sign now rather than emitting abs(): the value is already
        # known, and the shipped query must not depend on builtins being in scope.
        return TracedValue(
            abs(self.value), self.expr if self.value >= 0 else f"(-{self.expr})"
        )

    def __neg__(self) -> "TracedValue":
        return TracedValue(-self.value, f"(-{self.expr})")


def _num(value: Any) -> Any:
    """float() that lets a TracedValue through, so tracing survives context building."""
    return value if isinstance(value, TracedValue) else float(value)


@dataclass(frozen=True)
class Metric:
    id: str
    unit_kind: str
    description: str
    formula: Callable[[dict[str, float]], float | None] | None = None
    planner_visible: bool = True


_RAW_METRICS = (
    Metric("net_revenue", "money", "Doanh thu thuần"),
    Metric("cogs", "money", "Giá vốn hàng bán", planner_visible=False),
    Metric("gross_profit", "money", "Lợi nhuận gộp"),
    Metric("operating_profit", "money", "Lợi nhuận thuần từ hoạt động kinh doanh"),
    Metric("profit_before_tax", "money", "Lợi nhuận trước thuế"),
    Metric("net_profit", "money", "Lợi nhuận sau thuế"),
    Metric("net_profit_attributable_to_owners", "money", "LNST thuộc cổ đông công ty mẹ"),
    Metric("interest_expense", "money", "Chi phí lãi vay"),
    Metric("net_cash_operating", "money", "Lưu chuyển tiền thuần từ HĐKD"),
    Metric("total_assets", "money", "Tổng tài sản"),
    Metric("total_debt", "money", "Tổng nợ phải trả"),
    Metric("equity", "money", "Vốn chủ sở hữu"),
    Metric("owners_equity", "money", "Vốn góp/chủ sở hữu theo mã 410"),
    Metric("current_assets", "money", "Tài sản ngắn hạn"),
    Metric("short_term_debt", "money", "Nợ ngắn hạn mã 310"),
    Metric("inventory", "money", "Hàng tồn kho"),
    Metric("fixed_assets", "money", "Tài sản cố định", planner_visible=False),
    Metric("prev_net_revenue", "money", "Doanh thu thuần năm trước", planner_visible=False),
    Metric("prev_operating_profit", "money", "Lợi nhuận thuần HĐKD năm trước", planner_visible=False),
    Metric("avg_fixed_assets", "money", "Bình quân tài sản cố định", planner_visible=False),
)


_DERIVED_METRICS = (
    Metric("de_ratio", "ratio", "D/E = total_debt / equity", lambda m: _safe_div(m["total_debt"], m["equity"])),
    Metric(
        "roe",
        "ratio",
        "ROE = net_profit / average equity when available",
        lambda m: _safe_div(m["net_profit"], m.get("avg_equity", m.get("equity", m.get("owners_equity")))),
    ),
    Metric(
        "roa",
        "ratio",
        "ROA = net_profit_attributable_to_owners / total_assets",
        lambda m: _safe_div(m.get("net_profit_attributable_to_owners", m.get("net_profit", 0)), m["total_assets"]),
    ),
    Metric("gross_margin", "ratio", "Biên lợi nhuận gộp", lambda m: _safe_div(m["gross_profit"], m["net_revenue"])),
    Metric("operating_margin", "ratio", "Biên lợi nhuận hoạt động", lambda m: _safe_div(m["operating_profit"], m["net_revenue"]), planner_visible=False),
    Metric(
        "net_margin",
        "ratio",
        "Biên lợi nhuận ròng",
        lambda m: _safe_div(m.get("net_profit_attributable_to_owners", m.get("net_profit", 0)), m["net_revenue"]),
    ),
    Metric("current_ratio", "ratio", "Hệ số thanh toán hiện hành", lambda m: _safe_div(m["current_assets"], m["short_term_debt"])),
    Metric("quick_ratio", "ratio", "Hệ số thanh toán nhanh", lambda m: _safe_div(m["current_assets"] - m.get("inventory", 0), m["short_term_debt"])),
    Metric("icr", "ratio", "Khả năng thanh toán lãi vay", lambda m: _safe_div(m["profit_before_tax"] + abs(m["interest_expense"]), abs(m["interest_expense"]))),
    Metric("debt_ratio", "ratio", "Tỷ số nợ = total_debt / total_assets", lambda m: _safe_div(m["total_debt"], m["total_assets"])),
    Metric("cash_ratio", "ratio", "CFO / net_revenue", lambda m: _safe_div(m["net_cash_operating"], m["net_revenue"])),
    Metric("cfo_to_net_profit", "ratio", "CFO / net_profit", lambda m: _safe_div(m["net_cash_operating"], m["net_profit"])),
    Metric("cfo_to_short_term_debt", "ratio", "CFO / short_term_debt", lambda m: _safe_div(m["net_cash_operating"], m["short_term_debt"])),
    Metric("inventory_to_assets", "ratio", "inventory / total_assets", lambda m: _safe_div(m["inventory"], m["total_assets"])),
    Metric("net_profit_minus_cfo", "money", "net_profit - net_cash_operating", lambda m: m["net_profit"] - m["net_cash_operating"]),
    Metric(
        "revenue_growth",
        "ratio",
        "Tăng trưởng doanh thu thuần so với năm trước",
        lambda m: _safe_div(m["net_revenue"] - m["prev_net_revenue"], abs(m["prev_net_revenue"])),
        planner_visible=False,
    ),
    Metric(
        "operating_profit_growth",
        "ratio",
        "Tăng trưởng lợi nhuận thuần HĐKD so với năm trước",
        lambda m: _safe_div(m["operating_profit"] - m["prev_operating_profit"], abs(m["prev_operating_profit"])),
        planner_visible=False,
    ),
    Metric(
        "operating_leverage",
        "ratio",
        "Đòn bẩy kinh doanh = operating_profit_growth / revenue_growth",
        lambda m: _safe_div(m["operating_profit_growth"], m["revenue_growth"]),
        planner_visible=False,
    ),
    Metric("inventory_days", "ratio", "Số ngày tồn kho = inventory / abs(cogs) * 365", lambda m: _safe_div(m["inventory"], abs(m["cogs"])) * 365.0, planner_visible=False),
    Metric("fixed_asset_turnover", "ratio", "Vòng quay TSCĐ = net_revenue / average fixed_assets", lambda m: _safe_div(m["net_revenue"], m["avg_fixed_assets"]), planner_visible=False),
)


METRICS: dict[str, Metric] = {m.id: m for m in (*_RAW_METRICS, *_DERIVED_METRICS)}


def metric_ids() -> tuple[str, ...]:
    return tuple(METRICS)


def planner_metric_ids() -> tuple[str, ...]:
    return tuple(metric.id for metric in METRICS.values() if metric.planner_visible)


def metric_catalog() -> str:
    return "\n".join(
        f"- {metric.id} ({metric.unit_kind}): {metric.description}"
        for metric in METRICS.values()
        if metric.planner_visible
    )


def full_metric_catalog() -> str:
    return "\n".join(
        f"- {metric.id} ({metric.unit_kind}): {metric.description}"
        for metric in METRICS.values()
    )


def ratios_for(metrics: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    context = dict(metrics)
    for metric in _DERIVED_METRICS:
        try:
            value = metric.formula(context) if metric.formula else None
        except (KeyError, TypeError, ZeroDivisionError):
            value = None
        if value is not None and math.isfinite(value):
            out[metric.id] = value
            context[metric.id] = value
    return out


def metric_value(metrics: dict[str, float], metric_id: str) -> float | None:
    metric_id = str(metric_id).strip()
    if metric_id not in METRICS:
        return None
    if metric_id in metrics:
        value = metrics[metric_id]
    elif metric_id == "net_profit_attributable_to_owners" and "net_profit" in metrics:
        value = metrics["net_profit"]
    else:
        value = ratios_for(metrics).get(metric_id)
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def convert_unit(value: float, metric_id: str, unit_hint: str | None) -> float:
    unit_hint = (unit_hint or "").strip().lower()
    metric = METRICS.get(metric_id)
    if metric is None:
        return value
    if metric.unit_kind == "money":
        if unit_hint.startswith("nghìn tỷ"):
            return value / 1e12
        if unit_hint.startswith("trăm tỷ"):
            return value / 1e11
        if unit_hint.startswith("tỷ"):
            return value / 1e9
        if unit_hint.startswith("triệu"):
            return value / 1e6
        return value
    if metric.unit_kind == "ratio" and unit_hint in {"%", "phần trăm", "phan tram", "percent"}:
        return value * 100.0
    return value


def _metrics_with_context(ticker_data: dict[str, dict[str, float]], year: int) -> dict[str, float] | None:
    metrics = ticker_data.get(str(year))
    if metrics is None:
        return None
    row_metrics = dict(metrics)
    prev_metrics = ticker_data.get(str(year - 1))
    if prev_metrics:
        for key, value in prev_metrics.items():
            row_metrics.setdefault(f"prev_{key}", _num(value))
        for equity_key in ("equity", "owners_equity"):
            now = row_metrics.get(equity_key)
            prev = prev_metrics.get(equity_key)
            if now is not None and prev is not None:
                row_metrics.setdefault("avg_equity", (_num(now) + _num(prev)) / 2.0)
                break
        now_fixed_assets = row_metrics.get("fixed_assets")
        prev_fixed_assets = prev_metrics.get("fixed_assets")
        if now_fixed_assets is not None and prev_fixed_assets is not None:
            row_metrics.setdefault("avg_fixed_assets", (_num(now_fixed_assets) + _num(prev_fixed_assets)) / 2.0)
    return row_metrics


def _candidate_rows(data: CanonicalData, tickers: list[str] | None, years: list[int] | None) -> list[dict[str, Any]]:
    ticker_filter = {t.upper() for t in tickers or []}
    year_filter = {str(y) for y in years or []}
    rows: list[dict[str, Any]] = []
    for ticker, ticker_data in data.items():
        if ticker_filter and ticker.upper() not in ticker_filter:
            continue
        for year, metrics in ticker_data.items():
            if year_filter and year not in year_filter:
                continue
            row_metrics = _metrics_with_context(ticker_data, int(year))
            if row_metrics is None:
                continue
            rows.append({"ticker": ticker, "year": int(year), "metrics": row_metrics})
    return sorted(rows, key=lambda r: (r["ticker"], r["year"]))


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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _apply_filters(rows: list[dict[str, Any]], filters: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    kept = list(rows)
    for filt in filters:
        metric_id = str(filt.get("metric") or "").strip()
        op = str(filt.get("op") or "").strip()
        if metric_id not in METRICS:
            return None
        if op in {"below_median", "above_median"}:
            values = [v for row in kept if (v := metric_value(row["metrics"], metric_id)) is not None]
            med = _median(values)
            if med is None:
                return None
            op = "<" if op == "below_median" else ">"
            threshold = med
        else:
            try:
                threshold = float(filt.get("value"))
            except (TypeError, ValueError):
                return None
        next_rows = []
        for row in kept:
            value = metric_value(row["metrics"], metric_id)
            if value is not None and _compare(value, op, threshold):
                next_rows.append(row)
        kept = next_rows
    return kept


def _pick_row(rows: list[dict[str, Any]], select: dict[str, Any]) -> dict[str, Any] | None:
    metric_id = str(select.get("metric") or select.get("by", {}).get("metric") or "").strip()
    direction = str(select.get("direction") or "").strip().lower()
    if metric_id not in METRICS or direction not in {"max", "min"}:
        return None
    scored = []
    for row in rows:
        value = metric_value(row["metrics"], metric_id)
        if value is not None:
            scored.append((value, row))
    if not scored:
        return None
    return (max if direction == "max" else min)(scored, key=lambda item: item[0])[1]


def execute_canonical_plan(
    data: CanonicalData,
    plan: dict[str, Any],
    *,
    default_tickers: list[str] | None = None,
    default_years: list[int] | None = None,
    unit_hint: str | None = None,
    resolved: dict[str, Any] | None = None,
) -> tuple[float, str] | None:
    """Execute a validated canonical query plan.

    Supported plan shape:
    {
      "universe": {"tickers": [...], "years": [...]},
      "filters": [{"metric": "net_profit", "op": ">", "value": 0}],
      "select": {"metric": "quick_ratio", "direction": "min", "offset_years": 1},
      "answer": {"metric": "icr", "unit": "lần"}
    }

    On success, `resolved` (when given) records the row and unit the answer was
    read from, so the caller can rebuild it as a runnable pandas expression.
    """
    if not isinstance(plan, dict):
        return None

    universe = plan.get("universe") if isinstance(plan.get("universe"), dict) else {}
    tickers = default_tickers or universe.get("tickers") or []
    years = default_years or universe.get("years") or []
    try:
        years = [int(y) for y in years]
    except (TypeError, ValueError):
        return None

    rows = _candidate_rows(data, tickers, years)
    if not rows:
        return None

    filters = plan.get("filters") or []
    if not isinstance(filters, list):
        return None
    rows = _apply_filters(rows, filters)
    if not rows:
        return None

    select = plan.get("select") or {}
    if select:
        if not isinstance(select, dict):
            return None
        selected = _pick_row(rows, select)
        if selected is None:
            return None
        try:
            offset_years = int(select.get("offset_years") or 0)
            selected_year = int(selected["year"]) + offset_years
        except (TypeError, ValueError):
            return None
        if offset_years:
            ticker_data = data.get(selected["ticker"], {})
            selected_metrics = _metrics_with_context(ticker_data, selected_year)
            if selected_metrics is None:
                return None
            selected = {"ticker": selected["ticker"], "year": selected_year, "metrics": selected_metrics}
    elif len(rows) == 1:
        selected = rows[0]
    else:
        return None

    answer = plan.get("answer")
    if not isinstance(answer, dict):
        return None
    answer_metric = str(answer.get("metric") or "").strip()
    if answer_metric not in METRICS:
        return None
    value = metric_value(selected["metrics"], answer_metric)
    if value is None:
        return None
    unit = answer.get("unit") or unit_hint
    converted = convert_unit(value, answer_metric, unit)
    if resolved is not None:
        resolved.update(
            ticker=selected["ticker"], year=selected["year"], metric=answer_metric, unit=unit
        )

    query = (
        f"canonical_plan(ticker={selected['ticker']},year={selected['year']},"
        f"answer={answer_metric}"
    )
    if select:
        select_metric = select.get("metric") or select.get("by", {}).get("metric")
        query += f",select={select_metric}.{select.get('direction')}"
        if select.get("offset_years"):
            query += f",offset_years={select.get('offset_years')}"
    if filters:
        query += f",filters={len(filters)}"
    query += ")"
    return converted, query


def pandas_expr_for_metric(
    data: CanonicalData,
    provenance: dict[tuple[str, str, str], tuple[str, int, int]],
    *,
    ticker: str,
    year: int | str,
    metric_id: str,
    unit: str | None,
    expected: float,
) -> str | None:
    """Rebuild `metric_id` for (ticker, year) as a runnable pandas expression.

    `provenance` maps (ticker, year, raw metric) -> (dataframe variable, row
    position, column position). Returns None unless every input cell is
    traceable and the rebuilt expression evaluates back to `expected` -- we
    never ship a query that disagrees with the answer we submit.
    """
    if metric_id not in METRICS or not provenance:
        return None
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return None

    traced: dict[str, dict[str, Any]] = {}
    for yr in (year_int, year_int - 1):
        cells = {
            name: TracedValue(float(value), f"{src[0]}.iloc[{src[1]}, {src[2]}]")
            for name, value in (data.get(ticker, {}).get(str(yr)) or {}).items()
            if (src := provenance.get((ticker, str(yr), name))) is not None
        }
        if cells:
            traced[str(yr)] = cells
    if str(year_int) not in traced:
        return None

    context = _metrics_with_context(traced, year_int)
    if context is None:
        return None
    cell = context.get(metric_id)
    if cell is None:
        cell = ratios_for(context).get(metric_id)
    if cell is None and metric_id == "net_profit_attributable_to_owners":
        cell = context.get("net_profit")
    if not isinstance(cell, TracedValue):
        return None

    cell = convert_unit(cell, metric_id, unit)
    if not isinstance(cell, TracedValue) or not math.isfinite(cell.value):
        return None
    if abs(cell.value - expected) > max(1e-9, abs(expected) * 1e-9):
        return None
    return cell.expr


def execute_nested_selection(
    data: CanonicalData,
    years: list[int] | None,
    rank_metric: str,
    direction: str,
    answer_metric: str,
) -> tuple[float, str] | None:
    """Compatibility helper for the previous single-ticker max/min shortcut."""
    if len(data) != 1:
        return None
    ticker = next(iter(data))
    plan = {
        "universe": {"tickers": [ticker], "years": years or []},
        "select": {"metric": rank_metric, "direction": direction},
        "answer": {"metric": answer_metric},
    }
    return execute_canonical_plan(data, plan)
