"""Offline tests for deterministic catalog-backed selection facts."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.selection_facts import (  # noqa: E402
    deterministic_selection_plan,
    should_attempt_selection_facts,
)
from finance_qa.modules.solve.structured_facts import execute_plan  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def close(got: float, expected: float, rel: float = 0.01) -> bool:
    return abs(got - expected) / max(abs(expected), 1.0) < rel


Q363 = (
    "Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, "
    "hệ số khả năng thanh toán lãi vay là bao nhiêu lần?"
)
Q553 = (
    "Trong nhóm BSR, PLX và PVT năm 2019, công ty có tỷ lệ nợ phải trả trên "
    "vốn chủ sở hữu cao nhất có tỷ lệ tổng của lợi nhuận trước thuế và chi "
    "phí lãi vay trên chi phí lãi vay là bao nhiêu lần?"
)
Q555 = (
    "Trong giai đoạn 2022–2024 của CTCP Tập đoàn C.E.O (CEO), xét các năm có "
    "tỷ lệ lợi nhuận sau thuế trên doanh thu thuần lớn hơn 10%, doanh thu "
    "thuần thấp nhất là bao nhiêu nghìn tỷ đồng?"
)
Q521 = (
    "Trong các năm 2021, 2023 và 2025, chi phí lãi vay của CTCP Tập đoàn Hà "
    "Đô trong năm có tổng số dư tiền và các khoản tương đương tiền cuối năm "
    "lớn nhất là bao nhiêu tỷ đồng?"
)
Q488 = (
    "Năm 2016, trong số các công ty AAA, DCM, DPM và GVR có tỷ lệ lợi nhuận "
    "sau thuế trên doanh thu thuần lớn hơn 10%, tổng doanh thu thuần của các "
    "công ty đó là bao nhiêu nghìn tỷ đồng?"
)
Q526 = (
    "Trong các năm 2023, 2024 và 2025, chi phí khác của CTCP Đầu tư Thế giới "
    "Di động trong năm có Lãi cơ bản và suy giảm trên mỗi cổ phiếu lớn nhất "
    "là bao nhiêu tỷ đồng?"
)
Q542 = (
    "Trong số CTCP Phân bón Dầu khí Cà Mau, Tổng CTCP Phân bón và Hóa chất "
    "Dầu khí, Tập đoàn Công nghiệp Cao su Việt Nam và CTCP Sản xuất Kinh doanh "
    "Xuất nhập khẩu Dịch vụ và Đầu tư Tân Bình, mức thay đổi trung bình từ năm "
    "2021 đến năm 2022 của tỷ lệ lợi nhuận gộp trên doanh thu thuần tại các "
    "công ty có doanh thu thuần năm 2022 tăng so với năm 2021 là bao nhiêu "
    "điểm phần trăm?"
)


plan = deterministic_selection_plan({
    "question": Q363,
    "tickers": ["KBC"],
    "years": [2016, 2017, 2018, 2019, 2020],
    "doc_type": "consolidated",
    "unit_hint": "lần",
})
check("q363 deterministic plan is supported", plan.supported)
check("q363 selector is D/E", plan.selector_metric == "de_ratio")
check("q363 answer is interest coverage", plan.answer_metric == "interest_coverage")
check("q363 executes", close(execute_plan(plan, question=Q363)["answer"], 3.319357071984094))


plan = deterministic_selection_plan({
    "question": Q553,
    "tickers": ["BSR", "PLX", "PVT"],
    "years": [2019],
    "doc_type": "consolidated",
    "unit_hint": "lần",
})
check("q553 deterministic plan is supported", plan.supported)
check("q553 selector is D/E, not debt/assets", plan.selector_metric == "de_ratio")
check("q553 formula wording maps to interest coverage", plan.answer_metric == "interest_coverage")
check("q553 executes", close(execute_plan(plan, question=Q553)["answer"], 8.138020523057806))


plan = deterministic_selection_plan({
    "question": Q555,
    "tickers": ["CEO"],
    "years": [2022, 2023, 2024],
    "doc_type": "unknown",
    "unit_hint": "nghìn tỷ đồng",
})
check("q555 deterministic plan links filter", plan.supported)
check("q555 filter is net margin > 10%", plan.filters[0].metric == "net_margin")
check("q555 filter threshold is ratio-scaled", abs(float(plan.filters[0].value) - 0.10) < 1e-9)
check("q555 selector answers net revenue", plan.selector_metric == "net_revenue" and plan.answer_metric == "net_revenue")


plan = deterministic_selection_plan({
    "question": Q521,
    "tickers": ["HDG"],
    "years": [2021, 2023, 2025],
    "doc_type": "unknown",
    "unit_hint": "tỷ đồng",
})
check("q521 selector is cash", plan.selector_metric == "cash_and_equivalents")
check("q521 answer-first metric is interest expense", plan.answer_metric == "interest_expense")


for name, state in [
    (
        "conditional aggregate is outside deterministic selection_facts",
        {"question": Q488, "tickers": ["AAA", "DCM", "DPM", "GVR"], "years": [2016]},
    ),
    (
        "non-catalog EPS/other-expense selection is unsupported",
        {"question": Q526, "tickers": ["MWG"], "years": [2023, 2024, 2025]},
    ),
    (
        "multi-axis change question is unsupported",
        {"question": Q542, "tickers": ["DCM", "DPM", "GVR", "TIX"], "years": [2021, 2022]},
    ),
]:
    attempt, reason = should_attempt_selection_facts(state)
    check(name, not attempt and bool(reason))


print("tất cả PASS")
