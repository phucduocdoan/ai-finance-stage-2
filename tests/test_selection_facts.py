"""Offline tests for deterministic catalog-backed selection facts."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.facts.structured_facts import (  # noqa: E402
    StructuredFactError,
    execute_plan,
)
from finance_qa.modules.solve.solvers.selection_facts import (  # noqa: E402
    deterministic_selection_plan,
    should_attempt_selection_facts,
)


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


# --- filter -> aggregate: no extremum to rank by, just a filtered group -----

Q366 = (
    "Năm 2024, có bao nhiêu doanh nghiệp trong nhóm mã cổ phiếu HPX, NVL, SCR, "
    "VIC và VRE đồng thời ghi nhận vốn lưu động ròng âm và lưu chuyển tiền "
    "thuần từ hoạt động kinh doanh dương?"
)
Q368 = (
    "Năm 2022, trong nhóm HPG, HSG, MSR và NKG, các công ty có hệ số thanh toán "
    "nhanh thấp hơn trung vị của nhóm có biên lợi nhuận ròng bình quân là bao "
    "nhiêu phần trăm?"
)
Q404 = (
    "Năm 2024, trong các doanh nghiệp ngành hóa chất (bao gồm các công ty DCM, "
    "DPM, GVR), nhóm có hệ số nợ phải trả trên vốn chủ sở hữu cao hơn trung vị "
    "của nhóm chiếm bao nhiêu phần trăm tổng chi phí lãi vay của cả nhóm?"
)

plan = deterministic_selection_plan({
    "question": Q366,
    "tickers": ["HPX", "NVL", "SCR", "VIC", "VRE"],
    "years": [2024],
})
check("q366 counts the survivors of two sign filters", plan.supported)
check("q366 is a filter_aggregate", plan.operation == "filter_aggregate")
check("q366 aggregation is count", plan.aggregation == "count")
check(
    "q366 reads both signs off the metric named before each",
    [(f.metric, f.relation, f.value) for f in plan.filters]
    == [("working_capital", "lt", 0.0), ("cfo", "gt", 0.0)],
)
check("q366 count needs no answer metric", plan.answer_metric == "")

plan = deterministic_selection_plan({
    "question": Q368,
    "tickers": ["HPG", "HSG", "MSR", "NKG"],
    "years": [2022],
    "unit_hint": "phần trăm",
})
check("q368 filters on the group's own median", plan.supported)
check(
    "q368 median filter carries no literal value",
    [(f.metric, f.relation, f.value_source) for f in plan.filters]
    == [("quick_ratio", "lt", "median")],
)
check("q368 averages net margin over the survivors", plan.aggregation == "mean" and plan.answer_metric == "net_margin")
# Hand-checked against the raw ma_so rows: quick ratios (100-140)/310 are HPG
# 0.7377, HSG 0.4060, NKG 0.4210, MSR 0.3130, median 0.4135, so HSG and MSR
# survive; their net margins 60/10 are 0.5056% and 0.6762%.
check("q368 executes to the mean of the two survivors", close(execute_plan(plan, question=Q368)["answer"], 0.590899365626417))

plan = deterministic_selection_plan({
    "question": Q404,
    "tickers": ["DCM", "DPM", "GVR"],
    "years": [2024],
    "unit_hint": "phần trăm",
})
check("q404 is a group share", plan.supported and plan.aggregation == "share")
check("q404 shares out interest expense", plan.answer_metric == "interest_expense")
# D/E 300/400: DCM 0.5455, DPM 0.4805, GVR 0.4279. Above the median of three is
# DCM alone, and its interest expense is 9.9704% of the trio's.
check("q404 divides by the whole group", close(execute_plan(plan, question=Q404)["answer"], 9.970432097097923))

plan = deterministic_selection_plan({
    "question": Q488,
    "tickers": ["AAA", "DCM", "DPM", "GVR"],
    "years": [2016],
})
check("q488 sums the survivors of a threshold filter", plan.supported and plan.aggregation == "sum")
check("q488 answers in the question's own unit", plan.answer_metric == "net_revenue" and plan.target_unit == "trillion_vnd")
# A peer the fact store cannot read makes the sum wrong rather than approximate,
# so `missing_policy="fail"` must abort instead of aggregating three of four.
try:
    execute_plan(plan, question=Q488)
    check("q488 fails closed on an unreadable peer", False)
except StructuredFactError as exc:
    check("q488 fails closed on an unreadable peer", "DPM 2016" in str(exc))


# --- clauses the filter -> aggregate shape has no slot for -------------------
# Each of these builds a plausible-looking plan if the offending clause is
# dropped, which is worse than declining: it would displace codegen with a
# confidently wrong catalog number.

for name, state in [
    (
        "non-catalog EPS/other-expense selection is unsupported",
        {"question": Q526, "tickers": ["MWG"], "years": [2023, 2024, 2025]},
    ),
    (
        "multi-axis change question is unsupported",
        {"question": Q542, "tickers": ["DCM", "DPM", "GVR", "TIX"], "years": [2021, 2022]},
    ),
    (
        "scenario adjustment is not silently dropped",
        {
            "question": (
                "Trong năm 2023, xét tập hợp CRE, HPX, KBC, KHG, NVL, SNZ, SSH, "
                "VIC, VPI và VRE. Trong nhóm có hệ số nợ phải trả trên tổng tài "
                "sản cao hơn trung vị của tập hợp, tổng nợ phải trả của các "
                "doanh nghiệp có giá trị tài sản ròng chịu áp lực thanh lý âm "
                "(sau khi giảm 30% giá trị phải thu ngắn hạn và dài hạn, giảm "
                "50% giá trị hàng tồn kho, giữ nguyên các tài sản và nợ phải "
                "trả khác) chiếm bao nhiêu phần trăm tổng nợ phải trả của chính "
                "nhóm sau lọc này?"
            ),
            "tickers": ["CRE", "HPX", "KBC", "KHG", "NVL", "SNZ", "SSH", "VIC", "VPI", "VRE"],
            "years": [2023],
        },
    ),
    (
        "a composite metric the catalog cannot name is unsupported",
        {
            "question": (
                "Năm 2024, xét các doanh nghiệp có mã cổ phiếu ACV, DLG, HHV và "
                "VSC, trong nhóm có tỷ lệ tài sản ngắn hạn chia cho nợ ngắn hạn "
                "thấp hơn mức trung vị của cả 4 doanh nghiệp, tỷ lệ lợi nhuận "
                "gộp trên doanh thu thuần bình quân là bao nhiêu phần trăm?"
            ),
            "tickers": ["ACV", "DLG", "HHV", "VSC"],
            "years": [2024],
        },
    ),
    (
        "comparing two metrics to each other is not a filter",
        {
            "question": (
                "Năm 2024, trong các doanh nghiệp có mã cổ phiếu HPX, NVL, SCR, "
                "VIC và VRE, có bao nhiêu doanh nghiệp vừa có tài sản ngắn hạn "
                "thấp hơn nợ ngắn hạn vừa có lưu chuyển tiền thuần từ hoạt động "
                "kinh doanh dương?"
            ),
            "tickers": ["HPX", "NVL", "SCR", "VIC", "VRE"],
            "years": [2024],
        },
    ),
    (
        "difference between two subgroups is not one aggregate",
        {
            "question": (
                "Năm 2021, đối với nhóm DCM, DPM, GVR, PRT, chênh lệch về hệ số "
                "khả năng thanh toán lãi vay bình quân giữa phân nhóm có tỷ số "
                "D/E cao hơn trung vị và phân nhóm còn lại là bao nhiêu lần?"
            ),
            "tickers": ["DCM", "DPM", "GVR", "PRT"],
            "years": [2021],
        },
    ),
    (
        "a conditioned share denominator is unsupported",
        {
            "question": (
                "Năm 2024, xét 7 doanh nghiệp có mã cổ phiếu VIC, NVL, VRE, KBC, "
                "SCR, VPI và HPX. Các doanh nghiệp có tỷ lệ nợ phải trả trên "
                "tổng tài sản thấp hơn mức trung vị của 7 doanh nghiệp này đóng "
                "góp bao nhiêu phần trăm vào tổng lợi nhuận sau thuế của các "
                "doanh nghiệp có lãi?"
            ),
            "tickers": ["HPX", "KBC", "NVL", "SCR", "VIC", "VPI", "VRE"],
            "years": [2024],
        },
    ),
    (
        "a filter that must hold across several years is unsupported",
        {
            "question": (
                "Trong nhóm HPG, HSG, MSR và NKG có tỷ lệ lợi nhuận sau thuế "
                "trên doanh thu thuần dương trong cả ba năm 2020–2022, tổng "
                "doanh thu thuần năm 2022 của các công ty đó là bao nhiêu nghìn "
                "tỷ đồng?"
            ),
            "tickers": ["HPG", "HSG", "MSR", "NKG"],
            "years": [2022],
        },
    ),
    (
        "a group member the question never names is unsupported",
        {
            # Retrieval returns MSN alongside the three companies the question
            # actually lists, and for a count the group size *is* the answer.
            "question": (
                "Có bao nhiêu công ty trong số công ty mẹ CTCP Tập đoàn Hoa Sen, "
                "công ty mẹ CTCP Tập đoàn Hòa Phát và công ty mẹ CTCP Masan "
                "High-Tech Materials có lưu chuyển tiền thuần từ hoạt động kinh "
                "doanh dương trong năm 2022?"
            ),
            "tickers": ["HPG", "HSG", "MSN", "MSR"],
            "years": [2022],
        },
    ),
]:
    attempt, reason = should_attempt_selection_facts(state)
    check(name, not attempt and bool(reason))


print("tất cả PASS")
