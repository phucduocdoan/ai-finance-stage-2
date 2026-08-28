"""Deterministic formula and row-label hints for common financial ratios.

`understand.metric` is useful only if the solver sees what the metric means in
the row language of Vietnamese statements. These hints are deliberately small:
they do not solve the question, they just name the primitive rows a derived
ratio is made from so codegen stops looking for a non-existent row named "D/E"
or "quick ratio".
"""
from __future__ import annotations

from dataclasses import dataclass

from finance_qa.modules.solve.common.intent import norm as _norm


def _contains(norm_text: str, norm_alias: str) -> bool:
    if not norm_alias:
        return False
    return f" {norm_alias} " in f" {norm_text} "


@dataclass(frozen=True)
class MetricHint:
    """One formula hint, selected by metric key or by text aliases.

    Cross-reference: `finance_qa.modules.solve.facts.metrics.DERIVED_ALIASES`
    also carries Vietnamese alias phrases per ratio, but for a different job —
    labeling structural facts and canonicalizing planner/user text to a
    metric key — not matching a raw question against a formula/row-label
    hint (see `matches` below). The two alias lists overlap (many of the
    same ratios, similar core phrases) but are NOT identical: each has
    phrasing the other lacks, and neither is a subset of the other. They are
    kept deliberately separate rather than merged, since unifying them risks
    changing either this question-to-hint matching or the structural-fact
    matching in metrics.py in ways that are hard to fully verify without the
    eval set. When adding a new ratio alias, check both catalogs — this one
    and `metrics.DERIVED_ALIASES` — rather than assuming one is canonical.
    """

    name: str
    keys: tuple[str, ...]
    aliases: tuple[str, ...]
    formula: str
    rows: tuple[str, ...]
    search_labels: tuple[str, ...]
    note: str = ""

    def matches(self, metric: str, norm_question: str) -> bool:
        metric_norm = _norm(metric)
        return metric_norm in {_norm(key) for key in self.keys} or any(
            _contains(norm_question, _norm(alias)) for alias in self.aliases
        )

    def render(self) -> str:
        rows = "; ".join(self.rows)
        note = f" {self.note}" if self.note else ""
        return f"- {self.name}: {self.formula}. Dòng cơ sở: {rows}.{note}"


_HINTS: tuple[MetricHint, ...] = (
    MetricHint(
        "D/E hoặc nợ phải trả trên vốn chủ sở hữu",
        ("de_ratio", "debt_to_equity", "d e"),
        (
            "D/E", "tỷ số nợ trên vốn chủ sở hữu",
            "hệ số nợ phải trả trên vốn chủ sở hữu",
            "tỷ lệ nợ phải trả trên vốn chủ sở hữu",
            "nợ phải trả chia cho vốn chủ sở hữu",
            "nợ phải trả trên vốn chủ sở hữu",
        ),
        "Nợ phải trả / Vốn chủ sở hữu",
        ("Tổng nợ phải trả hoặc NỢ PHẢI TRẢ", "Vốn chủ sở hữu hoặc Tổng vốn chủ sở hữu"),
        ("Tổng nợ phải trả", "Nợ phải trả", "Vốn chủ sở hữu", "Tổng vốn chủ sở hữu"),
    ),
    MetricHint(
        "Nợ phải trả trên tổng tài sản",
        ("debt_to_assets", "liabilities_to_assets"),
        (
            "hệ số nợ phải trả trên tổng tài sản",
            "tỷ lệ nợ phải trả trên tổng tài sản",
            "nợ phải trả chia cho tổng tài sản",
            "nợ phải trả trên tổng tài sản",
        ),
        "Nợ phải trả / Tổng tài sản",
        ("Tổng nợ phải trả hoặc NỢ PHẢI TRẢ", "Tổng tài sản hoặc TÀI SẢN"),
        ("Tổng nợ phải trả", "Nợ phải trả", "Tổng tài sản"),
    ),
    MetricHint(
        "Hệ số thanh toán nhanh",
        ("quick_ratio",),
        ("hệ số thanh toán nhanh", "quick ratio"),
        "(Tài sản ngắn hạn - Hàng tồn kho) / Nợ ngắn hạn",
        ("Tài sản ngắn hạn", "Hàng tồn kho", "Nợ ngắn hạn"),
        ("Tài sản ngắn hạn", "Hàng tồn kho", "Nợ ngắn hạn", "Nợ phải trả ngắn hạn"),
    ),
    MetricHint(
        "Hệ số thanh toán hiện hành",
        ("current_ratio",),
        ("hệ số thanh toán hiện hành", "current ratio"),
        "Tài sản ngắn hạn / Nợ ngắn hạn",
        ("Tài sản ngắn hạn", "Nợ ngắn hạn"),
        ("Tài sản ngắn hạn", "Nợ ngắn hạn", "Nợ phải trả ngắn hạn"),
    ),
    MetricHint(
        "Vốn lưu động ròng",
        ("net_working_capital", "working_capital"),
        ("vốn lưu động ròng", "tài sản ngắn hạn thấp hơn nợ ngắn hạn"),
        "Tài sản ngắn hạn - Nợ ngắn hạn",
        ("Tài sản ngắn hạn", "Nợ ngắn hạn"),
        ("Tài sản ngắn hạn", "Nợ ngắn hạn", "Nợ phải trả ngắn hạn"),
    ),
    MetricHint(
        "Biên lợi nhuận gộp",
        ("gross_margin",),
        ("biên lợi nhuận gộp", "lợi nhuận gộp trên doanh thu thuần"),
        "Lợi nhuận gộp / Doanh thu thuần",
        ("Lợi nhuận gộp", "Doanh thu thuần"),
        ("Lợi nhuận gộp", "Doanh thu thuần"),
        "Nếu câu hỏi hỏi phần trăm, nhân 100.",
    ),
    MetricHint(
        "Biên lợi nhuận ròng",
        ("net_margin",),
        ("biên lợi nhuận ròng", "lợi nhuận sau thuế trên doanh thu thuần"),
        "Lợi nhuận sau thuế / Doanh thu thuần",
        ("Lợi nhuận sau thuế", "Doanh thu thuần"),
        ("Lợi nhuận sau thuế", "Doanh thu thuần"),
        "Nếu câu hỏi hỏi phần trăm, nhân 100.",
    ),
    MetricHint(
        "ROE",
        ("roe", "return_on_equity"),
        (
            "ROE", "tỷ suất lợi nhuận trên vốn chủ sở hữu",
            "tỷ suất lợi nhuận sau thuế trên vốn chủ sở hữu",
            "lợi nhuận sau thuế chia cho vốn chủ sở hữu",
            "lợi nhuận sau thuế trên vốn chủ sở hữu",
            "sinh lời trên vốn chủ sở hữu",
        ),
        "Lợi nhuận sau thuế / Vốn chủ sở hữu",
        ("Lợi nhuận sau thuế", "Vốn chủ sở hữu hoặc Tổng vốn chủ sở hữu"),
        ("Lợi nhuận sau thuế", "Vốn chủ sở hữu", "Tổng vốn chủ sở hữu"),
        "Nếu câu hỏi nói bình quân, lấy bình quân vốn chủ sở hữu đầu và cuối kỳ.",
    ),
    MetricHint(
        "ROA",
        ("roa", "return_on_assets"),
        (
            "ROA", "tỷ suất lợi nhuận trên tổng tài sản",
            "lợi nhuận sau thuế chia cho tổng tài sản",
            "lợi nhuận sau thuế trên tổng tài sản",
            "sinh lời trên tài sản",
        ),
        "Lợi nhuận sau thuế / Tổng tài sản",
        ("Lợi nhuận sau thuế", "Tổng tài sản hoặc TÀI SẢN"),
        ("Lợi nhuận sau thuế", "Tổng tài sản"),
        "Nếu câu hỏi nói bình quân, lấy bình quân tổng tài sản đầu và cuối kỳ.",
    ),
    MetricHint(
        "Hệ số khả năng thanh toán lãi vay",
        ("icr", "interest_coverage_ratio", "interest_coverage"),
        (
            "hệ số khả năng thanh toán lãi vay",
            "hệ số thanh toán lãi vay",
            "interest coverage",
            "ICR",
            "lợi nhuận trước lãi vay và thuế",
        ),
        "(Lợi nhuận trước thuế + Chi phí lãi vay) / Chi phí lãi vay",
        ("Lợi nhuận trước thuế", "Chi phí lãi vay"),
        ("Lợi nhuận trước thuế", "Chi phí lãi vay"),
    ),
    MetricHint(
        "CFO/LNST",
        ("cfo_to_net_profit", "cash_flow_to_net_profit"),
        (
            "CFO/LNST", "CFO trên LNST", "dòng tiền hoạt động trên lợi nhuận sau thuế",
            "lưu chuyển tiền thuần từ hoạt động kinh doanh trên lợi nhuận sau thuế",
            "tỷ lệ dòng tiền kinh doanh trên lợi nhuận sau thuế",
            "hệ số chuyển đổi lợi nhuận",
        ),
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh / Lợi nhuận sau thuế",
        ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Lợi nhuận sau thuế"),
        ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Lợi nhuận sau thuế"),
    ),
    MetricHint(
        "CFO/DTT",
        ("cfo_to_revenue", "operating_cash_flow_to_revenue"),
        (
            "CFO/DTT", "CFO trên doanh thu thuần",
            "dòng tiền hoạt động trên doanh thu thuần",
            "dòng tiền thuần từ hoạt động kinh doanh trên doanh thu thuần",
            "lưu chuyển tiền thuần từ hoạt động kinh doanh trên doanh thu thuần",
            "tỷ lệ dòng tiền hoạt động trên doanh thu thuần",
            "tỷ lệ dòng tiền thuần từ hoạt động kinh doanh trên doanh thu thuần",
        ),
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh / Doanh thu thuần",
        ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Doanh thu thuần"),
        ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Doanh thu thuần"),
    ),
    MetricHint(
        "CFO/nợ ngắn hạn",
        ("cfo_to_short_term_debt", "cfo_to_current_liabilities"),
        (
            "dòng tiền hoạt động trên nợ ngắn hạn",
            "lưu chuyển tiền thuần từ hoạt động kinh doanh trên nợ ngắn hạn",
            "hệ số dòng tiền hoạt động trên nợ ngắn hạn",
        ),
        "Lưu chuyển tiền thuần từ hoạt động kinh doanh / Nợ ngắn hạn",
        ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Nợ ngắn hạn"),
        ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Nợ ngắn hạn", "Nợ phải trả ngắn hạn"),
    ),
    MetricHint(
        "Tỷ trọng hàng tồn kho trên tổng tài sản",
        ("inventory_to_assets",),
        ("tỷ trọng hàng tồn kho trên tổng tài sản", "hàng tồn kho trên tổng tài sản"),
        "Hàng tồn kho / Tổng tài sản",
        ("Hàng tồn kho", "Tổng tài sản hoặc TÀI SẢN"),
        ("Hàng tồn kho", "Tổng tài sản"),
        "Nếu câu hỏi hỏi phần trăm, nhân 100.",
    ),
    MetricHint(
        "Vòng quay/ngày hàng tồn kho",
        ("inventory_days", "inventory_turnover"),
        ("vòng quay hàng tồn kho", "số ngày hàng tồn kho", "inventory days"),
        "Hàng tồn kho / Giá vốn hàng bán * 365",
        ("Hàng tồn kho", "Giá vốn hàng bán"),
        ("Hàng tồn kho", "Giá vốn hàng bán"),
    ),
    MetricHint(
        "Tăng trưởng doanh thu thuần",
        ("net_revenue_growth", "revenue_growth"),
        ("tốc độ tăng doanh thu thuần", "tăng trưởng doanh thu thuần"),
        "(Doanh thu thuần kỳ sau - Doanh thu thuần kỳ trước) / Doanh thu thuần kỳ trước",
        ("Doanh thu thuần",),
        ("Doanh thu thuần",),
        "Nếu câu hỏi hỏi phần trăm, nhân 100.",
    ),
)


def metric_hints(question: str, metric: str = "") -> list[MetricHint]:
    """Hints selected by the structured metric and by aliases in the question."""
    norm_question = _norm(question)
    selected: list[MetricHint] = []
    for hint in _HINTS:
        if hint.matches(metric, norm_question):
            selected.append(hint)
    return selected


def render_metric_hints(question: str, metric: str = "") -> str:
    """Prompt block for selected metric hints, or ``""`` when none apply."""
    hints = metric_hints(question, metric)
    if not hints:
        return ""
    lines = [
        "Gợi ý cách đọc chỉ tiêu:",
        "Không tìm một dòng có tên tỷ số nếu tỷ số phải tính từ các dòng cơ sở dưới đây.",
    ]
    lines.extend(hint.render() for hint in hints)
    return "\n".join(lines)


def metric_search_labels(label: str, metric: str = "") -> list[str]:
    """Primitive row labels to search when `label` names a derived metric."""
    out: list[str] = []
    for hint in metric_hints(label, metric):
        for row_label in hint.search_labels:
            if row_label not in out:
                out.append(row_label)
    return out


__all__ = ["MetricHint", "metric_hints", "metric_search_labels", "render_metric_hints"]
