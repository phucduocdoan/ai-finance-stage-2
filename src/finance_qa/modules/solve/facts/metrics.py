"""Metric catalog: primitive/derived aliases and text canonicalization."""
from __future__ import annotations

from dataclasses import dataclass

from finance_qa.modules.solve.common.intent import norm as _norm


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

# Cross-reference: `finance_qa.modules.solve.common.metric_hints._HINTS` also
# carries a `.aliases` field of Vietnamese phrases per ratio, but for a
# different job — matching free-form question text to a formula/row-label
# hint (`MetricHint.matches`), not labeling structural facts (`METRIC_KEYS`,
# `_RATIO_METRICS`, `canonical_metric`, `metrics_in_text` below). The two
# alias lists overlap (many of the same ratios, similar core phrases) but are
# NOT identical: each has phrasing the other lacks, and neither is a subset
# of the other. They are kept deliberately separate rather than merged, since
# unifying them risks changing either the structural-fact matching here or
# the question-to-hint matching in metric_hints.py in ways that are hard to
# fully verify without the eval set. When adding a new ratio alias, check
# both catalogs — this one and `metric_hints._HINTS` — rather than assuming
# one is canonical.
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


__all__ = [
    "DERIVED_ALIASES",
    "EXPRESSION_ALIASES",
    "EXPRESSION_KEYS",
    "EXPRESSION_SCHEMA_DESCRIPTION",
    "METRIC_KEYS",
    "METRIC_SCHEMA_DESCRIPTION",
    "PRIMITIVES",
    "PrimitiveMetric",
    "canonical_measure",
    "canonical_metric",
    "metric_source_unit",
    "metrics_in_text",
]
