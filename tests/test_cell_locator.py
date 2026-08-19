"""Offline tests for the deterministic single-cell locator."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.common import lookup  # noqa: E402
from finance_qa.modules.solve.solvers import cell_locator  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


FRAMES = {
    "BAB_2020_separate|6": pd.DataFrame({
        "STT": ["I", "II", "III"],
        "Chỉ tiêu": ["Tiền gửi của khách hàng", "TỔNG NỢ PHẢI TRẢ", "Tổng chi phí hoạt động"],
        "Thuyết minh": ["17", "", ""],
        "Số cuối năm Triệu đồng": [86564976.0, 108950874.0, -14733282.0],
        "Số đầu năm Triệu đồng": [76275540.0, 100170527.0, -11222333.0],
    }),
    "BAB_2020_separate|7": pd.DataFrame({
        "STT": ["I"],
        "Chỉ tiêu": ["TỔNG NỢ PHẢI TRẢ"],
        "Số cuối năm Triệu đồng": [108950874.0],
    }),
    "SSI_2016_separate|5": pd.DataFrame({
        "Chỉ tiêu": ["9. Phải thu các dịch vụ công ty chứng khoán cung cấp"],
        "Số cuối năm VND": [16280771391.0],
    }),
}

META = {
    "BAB_2020_separate|6": {"ticker": "BAB", "year": 2020, "doc_type": "separate"},
    "BAB_2020_separate|7": {"ticker": "BAB", "year": 2020, "doc_type": "separate"},
    "SSI_2016_separate|5": {"ticker": "SSI", "year": 2016, "doc_type": "separate"},
}


lookup.load_frame = lambda table_id: FRAMES[table_id]
lookup.meta_for = lambda table_id: META.get(table_id, {})
cell_locator.load_frame = lambda table_id: FRAMES[table_id]
cell_locator.meta_for = lambda table_id: META.get(table_id, {})
cell_locator.page_text = lambda table_id: ""


def state(question: str) -> dict:
    return {
        "question": question,
        "tickers": ["BAB"],
        "years": [2020],
        "metric": "total_debt",
        "operation": "lookup",
        "answer_shape": "single_cell",
        "multi_year": False,
        "multi_company": False,
        "doc_type": "separate",
        "unit_hint": "triệu đồng",
    }


hit, diag = cell_locator.locate_single_cell(
    state("Tổng nợ phải trả của công ty mẹ BAB đến ngày 31/12/2020 là bao nhiêu triệu đồng?"),
    table_ids=["BAB_2020_separate|6"],
    shortlist=["BAB_2020_separate|6"],
)
check("single-cell lookup locates a hit", hit is not None and diag["done"])
assert hit is not None
check("locator reads the label column after STT", hit.row_label == "TỔNG NỢ PHẢI TRẢ")
check("locator chooses the current/year-end column", hit.column == "Số cuối năm Triệu đồng")
check("locator builds an iloc query", hit.pandas_query == "df1.iloc[1]['Số cuối năm Triệu đồng']")
check("locator carries source unit from the column", hit.source_unit == "million_vnd")
check("locator carries requested target unit", hit.target_unit == "million_vnd")

prior, _ = cell_locator.locate_single_cell(
    state("Tổng nợ phải trả của công ty mẹ BAB vào đầu năm 2020 là bao nhiêu triệu đồng?"),
    table_ids=["BAB_2020_separate|6"],
    shortlist=["BAB_2020_separate|6"],
)
check("beginning-period questions choose the prior column", prior is not None and prior.column == "Số đầu năm Triệu đồng")

expense, expense_diag = cell_locator.locate_single_cell(
    {
        **state("Tổng chi phí hoạt động của công ty mẹ BAB năm 2020 là bao nhiêu triệu đồng?"),
        "metric": "operating_expense",
    },
    table_ids=["BAB_2020_separate|6"],
    shortlist=["BAB_2020_separate|6"],
)
check("expense questions ask for magnitude", expense is not None and expense.pandas_query.startswith("abs("))
check("expense transform is recorded on the request", expense_diag["request"]["value_transform"] == "abs")

cashflow_request, _ = cell_locator.build_request({
    **state("Lưu chuyển tiền thuần từ hoạt động kinh doanh của BAB năm 2020 là bao nhiêu triệu đồng?"),
    "metric": "net_cash_operating",
})
check("cash-flow questions stay signed", cashflow_request is not None and cashflow_request.value_transform == "as_reported")

fvtpl_phrases = cell_locator.direct_metric_phrases(
    "Giá trị hợp lý của tài sản tài chính loại FVTPL cuối năm 2019 của công ty mẹ SSI là bao nhiêu nghìn tỷ đồng?",
    "fvtpl_financial_assets",
)
check("metric-internal 'của' is not treated as the company scope", fvtpl_phrases[0] == "Giá trị hợp lý của tài sản tài chính loại FVTPL")

loan_phrases = cell_locator.direct_metric_phrases(
    "Tiền ngân hàng cho vay đối với cổ đông lớn của MBB cuối năm 2015 là bao nhiêu triệu đồng?",
    "interest_expense",
)
check("LLM metric aliases only join when supported by question text", "Lãi vay" not in loan_phrases)

ratio_request, ratio_reason = cell_locator.build_request({
    **state("Tỷ trọng tài sản cố định vô hình trong tổng tài sản cố định của BAB năm 2020 là bao nhiêu %?"),
    "metric": "fixed_assets_intangible_ratio",
    "operation": "formula",
    "answer_shape": "derived",
    "unit_hint": "%",
})
check("tỷ trọng is gated as derived", ratio_request is None and "derived" in ratio_reason)

component, component_diag = cell_locator.locate_single_cell(
    {
        **state("Tổng cộng các khoản phải thu của công ty mẹ SSI vào cuối năm 2016 là bao nhiêu tỷ đồng?"),
        "tickers": ["SSI"],
        "years": [2016],
        "metric": "accounts_receivable",
        "unit_hint": "tỷ đồng",
    },
    table_ids=["SSI_2016_separate|5"],
    shortlist=["SSI_2016_separate|5"],
)
check("a total request does not accept a component row", component is None and not component_diag["done"])

ambiguous, amb_diag = cell_locator.locate_single_cell(
    state("Tổng nợ phải trả của công ty mẹ BAB đến ngày 31/12/2020 là bao nhiêu triệu đồng?"),
    table_ids=["BAB_2020_separate|6", "BAB_2020_separate|7"],
    shortlist=["BAB_2020_separate|6", "BAB_2020_separate|7"],
)
check("near-tied cells fall back instead of guessing", ambiguous is None and amb_diag["reason"] == "ambiguous located cells")

derived, derived_diag = cell_locator.locate_single_cell(
    {
        **state("Tỷ suất lợi nhuận ròng của BAB năm 2020 là bao nhiêu %?"),
        "metric": "net_margin",
        "operation": "formula",
        "answer_shape": "derived",
        "unit_hint": "%",
    },
    table_ids=["BAB_2020_separate|6"],
    shortlist=["BAB_2020_separate|6"],
)
check("derived questions are gated out", derived is None and "derived" in derived_diag["reason"])

print("tất cả PASS")
