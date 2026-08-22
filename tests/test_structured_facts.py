"""Regression tests for the structured main-statement fact solver."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from pydantic import ValidationError  # noqa: E402

from finance_qa.modules.solve.facts.structured_facts import (  # noqa: E402
    PRIMITIVES,
    PlannerMetricFilter,
    StatementFactStore,
    StructuredFactError,
    StructuredPlannerOutput,
    StructuredSelectionPlan,
    StructuredPlan,
    UnsupportedStructuredPlan,
    canonical_metric,
    execute_plan,
    heuristic_plan,
    metrics_in_text,
    supported_v1_plan,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def close(got: float, expected: float, rel: float = 0.01) -> bool:
    return abs(got - expected) / max(abs(expected), 1.0) < rel


def check_raises(name: str, fn) -> None:
    try:
        fn()
    except StructuredFactError:
        print(f"ok   {name}")
        return
    raise AssertionError(name)


def check_validation_raises(name: str, fn) -> None:
    try:
        fn()
    except ValidationError:
        print(f"ok   {name}")
        return
    raise AssertionError(name)


Q363 = (
    "Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, "
    "hệ số khả năng thanh toán lãi vay là bao nhiêu lần?"
)
Q390 = (
    "Năm 2024, giá trị hàng tồn kho của doanh nghiệp có hệ số thanh toán nhanh "
    "thấp nhất trong 3 doanh nghiệp Hoà Phát, Hoa Sen, Nam Kim là bao nhiêu "
    "nghìn tỷ đồng?"
)
Q371 = (
    "Năm 2024, trong nhóm BSR, PLX và PVT, công ty có biên lợi nhuận gộp cao nhất "
    "trong số các công ty có lưu chuyển tiền thuần từ hoạt động kinh doanh dương "
    "có hệ số khả năng thanh toán lãi vay là bao nhiêu lần?"
)
Q378 = (
    "Trong giai đoạn 2018–2024 của HPG, xét các năm có biên lợi nhuận gộp thấp hơn "
    "trung vị của cả giai đoạn, ROE tại năm có tỷ số dòng tiền hoạt động trên "
    "doanh thu thuần cao nhất là bao nhiêu phần trăm?"
)
check("canonical D/E", canonical_metric("tỷ số D/E") == "de_ratio")
check("canonical ICR", canonical_metric("hệ số khả năng thanh toán lãi vay") == "interest_coverage")
check("metrics keep text order", metrics_in_text(Q363) == ["de_ratio", "interest_coverage"])

fallback = heuristic_plan(
    question=Q363, tickers=["KBC"], years=[2016, 2017, 2018, 2019, 2020],
    doc_type="consolidated", metric="", operation="compare", unit_hint="",
)
check("heuristic does not infer selection semantics", not fallback.supported)
check("heuristic preserves resolved axis only", fallback.axis == "year")

check_validation_raises(
    "planner schema rejects non-selection operations",
    lambda: StructuredSelectionPlan(
        operation="lookup", axis="year", selector_metric="de_ratio",
        selector_order="max", answer_metric="interest_coverage",
    ),
)
check_validation_raises(
    "planner schema rejects ambiguous conditional_select operation",
    lambda: StructuredSelectionPlan(
        operation="conditional_select", axis="year", selector_metric="de_ratio",
        selector_order="max", answer={"kind": "metric", "metric": "interest_coverage"},
    ),
)
check_validation_raises(
    "planner schema rejects scope fields as filters",
    lambda: PlannerMetricFilter(metric="ticker", relation="eq", value=1),
)
check_validation_raises(
    "planner answer branch forbids metric/expression conflicts",
    lambda: StructuredSelectionPlan.model_validate({
        "operation": "argmin",
        "axis": "ticker",
        "tickers": ["HPG", "HSG", "NKG"],
        "years": [2024],
        "selector_metric": "quick_ratio",
        "selector_order": "min",
        "answer": {
            "kind": "metric",
            "metric": "inventory",
            "expression": "inventory_days_excess_release",
        },
    }),
)

check(
    "planner root unsupported branch maps to fallback plan",
    not StructuredPlannerOutput(
        plan=UnsupportedStructuredPlan(reason="outside fact schema")
    ).to_structured_plan().supported,
)

planner_plan = StructuredSelectionPlan(
    operation="argmax", axis="year", tickers=["KBC"],
    years=[2016, 2017, 2018, 2019, 2020],
    doc_type="consolidated", selector_metric="de_ratio", selector_order="max",
    answer={"kind": "metric", "metric": "interest_coverage"}, target_unit="ratio",
)
check(
    "planner schema maps to executor plan",
    planner_plan.to_structured_plan().model_dump(exclude={"reason"})
    == StructuredPlan(
        operation="argmax", axis="year", tickers=["KBC"],
        years=[2016, 2017, 2018, 2019, 2020],
        doc_type="consolidated", selector_metric="de_ratio", selector_order="max",
        answer_metric="interest_coverage", target_unit="ratio",
    ).model_dump(exclude={"reason"}),
)
check(
    "planner drops incomplete selector-duplicate filters",
    StructuredSelectionPlan(
        operation="argmax", axis="year", tickers=["KBC"],
        years=[2016, 2017, 2018, 2019, 2020],
        selector_metric="de_ratio", selector_order="max",
        answer={"kind": "metric", "metric": "interest_coverage"},
        filters=[{"metric": "de_ratio", "relation": "gt"}],
    ).to_structured_plan().filters == [],
)
check(
    "planner drops equality filters on the selector metric",
    StructuredSelectionPlan(
        operation="argmin", axis="year", tickers=["HPG"],
        years=[2017, 2018, 2019, 2020, 2021, 2022, 2023],
        selector_metric="cfo_to_net_profit", selector_order="min",
        answer={"kind": "metric", "metric": "inventory_to_assets"},
        filters=[{"metric": "cfo_to_net_profit", "relation": "eq", "value_source": "median"}],
    ).to_structured_plan().filters == [],
)

plan = StructuredPlan(
    operation="argmax", axis="year", tickers=["KBC"],
    years=[2016, 2017, 2018, 2019, 2020],
    doc_type="consolidated", selector_metric="de_ratio", selector_order="max",
    answer_metric="interest_coverage", target_unit="ratio",
)
check("q363 is in v1 scope", supported_v1_plan(plan, Q363)[0])
check(
    "q390 is in v1 scope",
    supported_v1_plan(
        StructuredPlan(
            operation="argmin", axis="ticker", tickers=["HPG", "HSG", "NKG"], years=[2024],
            doc_type="consolidated", selector_metric="quick_ratio", selector_order="min",
            answer_metric="inventory", target_unit="trillion_vnd",
        ),
        Q390,
        "nghìn tỷ đồng",
    )[0],
)
check(
    "expression answer cannot conflict with a direct answer metric",
    not supported_v1_plan(
        StructuredPlan(
            operation="argmin", axis="ticker", tickers=["HPG", "HSG", "NKG"], years=[2024],
            doc_type="consolidated", selector_metric="quick_ratio", selector_order="min",
            answer_metric="inventory", answer_expression="inventory_days_excess_release",
            target_unit="trillion_vnd",
        ),
        Q390,
        "nghìn tỷ đồng",
    )[0],
)
check(
    "plain lookup is outside v1 scope",
    not supported_v1_plan(
        StructuredPlan(
            operation="lookup", tickers=["KBC"], years=[2020],
            doc_type="consolidated", answer_metric="equity",
        ),
        "Vốn chủ sở hữu của KBC năm 2020 là bao nhiêu?",
    )[0],
)
check(
    "question ratio unit overrides planner count target",
    supported_v1_plan(
        StructuredPlan(
            operation="argmax", axis="year", tickers=["KBC"],
            years=[2016, 2017, 2018, 2019, 2020],
            doc_type="consolidated", selector_metric="de_ratio",
            selector_order="max", answer_metric="interest_coverage",
            target_unit="count",
        ),
        Q363,
    )[0],
)
check(
    "ratio answer rejects non-ratio target without question hint",
    not supported_v1_plan(
        StructuredPlan(
            operation="argmax", axis="year", tickers=["KBC"],
            years=[2016, 2017, 2018, 2019, 2020],
            doc_type="consolidated", selector_metric="de_ratio",
            selector_order="max", answer_metric="interest_coverage",
            target_unit="count",
        ),
        "Select one year and return interest coverage.",
    )[0],
)

got = execute_plan(plan, question=Q363)["answer"]
check("q363 structured answer", close(got, 3.319357071984094))
check(
    "execute uses question ratio unit before planner target",
    execute_plan(
        StructuredPlan(
            operation="argmax", axis="year", tickers=["KBC"],
            years=[2016, 2017, 2018, 2019, 2020],
            doc_type="consolidated", selector_metric="de_ratio",
            selector_order="max", answer_metric="interest_coverage",
            target_unit="count",
        ),
        question=Q363,
    )["diag"]["target_unit"] == "ratio",
)

got = execute_plan(
    StructuredPlan(
        operation="argmax", axis="year", tickers=["HPG"],
        years=[2018, 2019, 2020, 2021, 2022, 2023, 2024],
        doc_type="consolidated", selector_metric="cfo_to_revenue",
        selector_order="max", answer_metric="roe", target_unit="percent",
        filters=[{"metric": "gross_margin", "relation": "lt", "value_source": "median"}],
    ),
    question=Q378,
)["answer"]
check("q378 structured answer uses average equity ROE", close(got, 9.036618))

got = execute_plan(
    StructuredPlan(
        operation="argmin", axis="ticker", tickers=["HPG", "HSG", "NKG"], years=[2024],
        doc_type="consolidated", selector_metric="quick_ratio", selector_order="min",
        answer_metric="inventory", target_unit="trillion_vnd",
    ),
    question=Q390,
)["answer"]
check("q390 structured answer", close(got, 6.690483))

got = execute_plan(
    StructuredPlan(
        operation="argmax", axis="ticker", tickers=["BSR", "PLX", "PVT"], years=[2024],
        doc_type="consolidated", selector_metric="gross_margin", selector_order="max",
        answer_metric="interest_coverage", target_unit="ratio",
        filter_metric="cfo", filter_relation="gt", filter_value=0,
        missing_policy="skip",
    ),
    question=Q371,
)["answer"]
check("q371 structured answer", close(got, 5.472919))

check_raises(
    "q372 offset answer falls back when target-year CFO is not covered",
    lambda: execute_plan(
        StructuredPlan(
            operation="argmin", axis="year", tickers=["VRE"],
            years=[2021, 2022, 2023, 2024], doc_type="consolidated",
            selector_metric="quick_ratio", selector_order="min",
            answer_metric="cfo_to_current_liabilities", year_offset=1,
        ),
        question=(
            "Công ty Vincom Retail có hệ số dòng tiền hoạt động trên nợ ngắn hạn "
            "vào năm sau năm có hệ số thanh toán nhanh thấp nhất trong giai đoạn "
            "2021-2024 là bao nhiêu lần?"
        ),
    ),
)

got = execute_plan(
    StructuredPlan(
        operation="argmin", axis="year", tickers=["MWG"], years=[2021, 2022, 2023],
        doc_type="consolidated", selector_metric="cfo_to_net_profit",
        selector_order="min", answer_metric="current_ratio", year_offset=1,
        filters=[{"metric": "net_profit", "relation": "gt", "value": 0}],
    ),
    question=(
        "Xét Công ty Cổ phần Đầu tư Thế Giới Di Động, trong các năm thuộc giai "
        "đoạn 2021-2023 có lợi nhuận sau thuế dương, hãy xác định năm có hệ số "
        "chuyển đổi lợi nhuận (CFO/LNST) thấp nhất; từ đó cho biết hệ số thanh "
        "toán hiện hành tại thời điểm cuối năm kế tiếp là bao nhiêu lần?"
    ),
)["answer"]
check("q407 year_offset=1 reads the next year's current ratio", close(got, 1.714506))

check_raises(
    "q396 fails closed when one peer has no fact coverage",
    lambda: execute_plan(
        StructuredPlan(
            operation="argmax", axis="ticker", tickers=["ASM", "DBC", "MSN", "OGC"],
            years=[2024], doc_type="unknown", selector_metric="cfo_to_net_profit",
            selector_order="max", answer_metric="quick_ratio",
            filters=[
                {"metric": "cfo", "relation": "gt", "value": 0},
                {"metric": "net_profit", "relation": "gt", "value": 0},
            ],
        ),
        question="Doanh nghiệp có CFO/LNST lớn nhất sau lọc có quick ratio bao nhiêu?",
    ),
)

got = execute_plan(
    StructuredPlan(
        operation="argmax", axis="year", tickers=["HPG"],
        years=[2020, 2021, 2022, 2023, 2024], doc_type="consolidated",
        selector_metric="net_revenue", selector_order="max",
        answer_metric="current_ratio",
    ),
    question=(
        "Tại năm mà Hoà Phát đạt doanh thu thuần cao nhất trong giai đoạn "
        "2020-2024, hệ số thanh toán hiện hành cuối năm là bao nhiêu lần?"
    ),
)["answer"]
check("q415 selector chooses the source-derived max-revenue year", close(got, 1.281728))

bank_lookup = execute_plan(
    StructuredPlan(
        operation="lookup", tickers=["BAB"], years=[2020], doc_type="separate",
        answer_metric="liabilities", target_unit="million_vnd",
    ),
    question="Tổng nợ phải trả của công ty mẹ BAB cuối năm 2020 là bao nhiêu triệu đồng?",
)
check("bank no-ma-so fallback scales liabilities to million VND", close(bank_lookup["answer"], 108_950_874))
check(
    "bank no-ma-so fallback records fact provenance",
    bank_lookup["diag"]["facts"][0]["fact_source"] == "bank_label_fallback",
)

got = execute_plan(
    StructuredPlan(
        operation="lookup", tickers=["SGB"], years=[2024], doc_type="consolidated",
        answer_metric="net_profit", target_unit="million_vnd",
    ),
    question="Lợi nhuận sau thuế của SGB năm 2024 là bao nhiêu triệu đồng?",
)["answer"]
check("bank no-ma-so fallback reads income-statement net profit", close(got, 79_168))

got = execute_plan(
    StructuredPlan(
        operation="ratio", tickers=["SGB"], years=[2015], doc_type="separate",
        answer_metric="debt_to_assets", target_unit="percent",
    ),
    question="Tỷ lệ nợ trên tổng tài sản của công ty mẹ SGB cuối năm 2015 là bao nhiêu phần trăm?",
)["answer"]
check("bank no-ma-so fallback supports debt/assets ratio", close(got, 14_968_812 / 18_359_429 * 100))

got = execute_plan(
    StructuredPlan(
        operation="ratio", tickers=["NVB"], years=[2016], doc_type="separate",
        answer_metric="cfo_to_profit_before_tax", target_unit="percent",
    ),
    question="Tỷ lệ dòng tiền thuần từ hoạt động kinh doanh trên lợi nhuận trước thuế của NVB năm 2016 là bao nhiêu %?",
)["answer"]
check("bank no-ma-so fallback supports CFO/PBT ratio", close(got, 2_970_254 / 13_380 * 100))

store = StatementFactStore()
fact = store.value(
    ticker="NVB", year=2019, doc_type="consolidated",
    metric=PRIMITIVES["total_assets"],
)
check("bank no-ma-so fallback can read total assets from continuation tables", close(fact.value, 80_394_022_000_000))
check("bank total assets fallback uses the gold table", fact.table_id == "NVB_financial_statements_2019_consolidated|4")

got = execute_plan(
    StructuredPlan(
        operation="argmin", axis="ticker", tickers=["GEX", "HBC", "PC1", "SAM", "VGC"],
        years=[2024], doc_type="consolidated",
        selector_metric="stress_interest_coverage", selector_order="min",
        answer_expression="stress_interest_coverage", scenario_factor=0.85,
        filters=[{"metric": "quick_ratio", "relation": "lt", "value_source": "median"}],
        target_unit="ratio", round_digits=2,
    ),
    question=(
        "Xét năm 2024 và các doanh nghiệp thuộc nhóm GEX, HBC, PC1, SAM, VGC có "
        "tỉ số thanh toán nhanh thấp hơn trung vị ngành, nếu EBIT proxy giảm 15%, "
        "hệ số khả năng thanh toán lãi vay thấp nhất theo kịch bản là bao nhiêu?"
    ),
)["answer"]
check("q423 scenario ICR is a whitelisted expression", close(got, 3.70))

got = execute_plan(
    StructuredPlan(
        operation="argmax", axis="ticker", tickers=["DCM", "GVR", "HT1"],
        years=[2024], doc_type="consolidated",
        selector_metric="inventory_days", selector_order="max",
        answer_expression="inventory_days_excess_release", target_unit="billion_vnd",
        filters=[{"metric": "inventory_days", "relation": "gt", "value_source": "median"}],
    ),
    question=(
        "Năm 2024, doanh nghiệp có số ngày tồn kho vượt trung vị ngành nhiều nhất "
        "có thể giải phóng ước tính bao nhiêu tỷ đồng nếu giảm số ngày tồn kho "
        "về đúng trung vị?"
    ),
)["answer"]
check("q424 DOH release uses the median excess expression", close(got, 480.26))

check_raises(
    "q426 CFO/LNST does not degrade to CFO when historical CFO facts are missing",
    lambda: execute_plan(
        StructuredPlan(
            operation="argmin", axis="year", tickers=["FPT"],
            years=[2021, 2022, 2023, 2024], doc_type="consolidated",
            selector_metric="cfo_to_net_profit", selector_order="min",
            answer_expression="net_profit_minus_cfo", target_unit="trillion_vnd",
            filters=[{"metric": "net_profit", "relation": "gt", "value": 0}],
        ),
        question="Năm có CFO/LNST thấp nhất và LNST dương, phần LNST chưa chuyển hóa thành CFO là bao nhiêu?",
    ),
)

check_raises(
    "q521 cash winner falls back when selected-year interest expense is not covered",
    lambda: execute_plan(
        StructuredPlan(
            operation="argmax", axis="year", tickers=["HDG"], years=[2021, 2023, 2025],
            doc_type="consolidated", selector_metric="cash_and_equivalents",
            selector_order="max", answer_metric="interest_expense", target_unit="billion_vnd",
        ),
        question="Năm tiền và tương đương tiền cuối năm lớn nhất, chi phí lãi vay là bao nhiêu?",
    ),
)

check_raises(
    "q555 unknown scope does not silently use separate facts when consolidated is absent",
    lambda: execute_plan(
        StructuredPlan(
            operation="argmin", axis="year", tickers=["CEO"], years=[2022, 2023, 2024],
            doc_type="unknown", selector_metric="net_revenue", selector_order="min",
            answer_metric="net_revenue", target_unit="trillion_vnd",
            filters=[{"metric": "net_margin", "relation": "gt", "value": 0.10}],
        ),
        question="Các năm có biên LNST trên doanh thu thuần >10%, doanh thu thuần thấp nhất là bao nhiêu?",
    ),
)


# --- filter_aggregate: aggregate the survivors instead of ranking them -------
# One case per aggregation, all on DCM/DPM/GVR 2024 so the same survivors and
# the same raw rows back every expectation. Every number below was computed by
# hand from the consolidated ma_so rows, not read off the executor:
#   net profit (60)  DCM 1_428_006_581_442  DPM   554_266_541_498  GVR  4_826_666_026_951
#   net revenue (10) DCM 13_455_585_149_640 DPM 13_496_142_223_703 GVR 26_241_944_114_845
#   liabilities(300) DCM  5_551_670_737_163 DPM  5_372_450_027_238 GVR 24_986_520_299_896
#   equity     (400) DCM 10_177_176_600_982 DPM 11_179_836_420_269 GVR 58_397_162_212_108
# All three are reported in plain VND, which keeps these expectations free of the
# thousand-VND scaling MSR's reports would bring in.
CHEM = dict(
    operation="filter_aggregate", axis="ticker", tickers=["DCM", "DPM", "GVR"],
    years=[2024], doc_type="consolidated",
)
PROFITABLE = [{"metric": "net_profit", "relation": "gt", "value": 0}]
CHEM_Q = "Năm 2024, xét nhóm DCM, DPM và GVR có lợi nhuận sau thuế dương."

# All three are profitable, so `count` is 3 -- and it gets there without reading
# an answer metric at all.
got = execute_plan(
    StructuredPlan(**CHEM, aggregation="count", filters=PROFITABLE), question=CHEM_Q,
)["answer"]
check("filter_aggregate count needs no answer metric", close(got, 3.0))

# 5551.670737163 + 5372.450027238 + 24986.520299896
got = execute_plan(
    StructuredPlan(**CHEM, aggregation="sum", answer_metric="liabilities",
                   filters=PROFITABLE, target_unit="billion_vnd"), question=CHEM_Q,
)["answer"]
check("filter_aggregate sum adds the survivors", close(got, 35910.641064297))

# median(5551.67, 5372.45, 24986.52) = DCM's
got = execute_plan(
    StructuredPlan(**CHEM, aggregation="median", answer_metric="liabilities",
                   filters=PROFITABLE, target_unit="billion_vnd"), question=CHEM_Q,
)["answer"]
check("filter_aggregate median picks the middle survivor", close(got, 5551.670737163))

# (10.612742334 + 4.106851664 + 18.392943777) / 3
got = execute_plan(
    StructuredPlan(**CHEM, aggregation="mean", answer_metric="net_margin",
                   filters=PROFITABLE, target_unit="percent"), question=CHEM_Q,
)["answer"]
check("filter_aggregate mean averages a ratio metric", close(got, 11.037512591527))

# D/E is DCM 0.5455, DPM 0.4805, GVR 0.4279, so only DCM is above the median of
# three -- and the denominator is the whole trio, not just the survivor.
got = execute_plan(
    StructuredPlan(
        **CHEM, aggregation="share", answer_metric="liabilities", target_unit="percent",
        filters=[{"metric": "de_ratio", "relation": "gt", "value_source": "median"}],
    ),
    question="Nhóm có D/E cao hơn trung vị chiếm bao nhiêu phần trăm tổng nợ phải trả của cả nhóm?",
)["answer"]
check("filter_aggregate share divides by the whole group", close(got, 15.459681511179063))

# An unreadable peer makes an aggregate wrong rather than approximate: NKG 2022
# has no consolidated cash-flow statement, so a CFO sign filter over a group
# containing it must abort instead of quietly aggregating the other three.
check_raises(
    "filter_aggregate fails closed when a peer cannot be read",
    lambda: execute_plan(
        StructuredPlan(
            operation="filter_aggregate", axis="ticker", tickers=["HPG", "HSG", "MSR", "NKG"],
            years=[2022], doc_type="consolidated", aggregation="count",
            filters=[{"metric": "cfo", "relation": "gt", "value": 0}],
        ),
        question="Năm 2022, bao nhiêu doanh nghiệp trong nhóm có CFO dương?",
    ),
)

print("tất cả PASS")
