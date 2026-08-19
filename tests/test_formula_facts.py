"""Offline tests for the deterministic formula-facts branch."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.facts.structured_facts import StructuredPlan, execute_plan  # noqa: E402
from finance_qa.modules.solve.solvers.formula_facts import (  # noqa: E402
    FormulaSupportedPlan,
    deterministic_formula_plan,
    execute_formula_plan,
    should_attempt_formula_facts,
    supported_formula_plan,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def close(got: float, expected: float, rel: float = 0.01) -> bool:
    return abs(got - expected) / max(abs(expected), 1.0) < rel


Q_RATIO = "Hệ số thanh toán hiện hành của HPG cuối năm 2024 là bao nhiêu lần?"
Q_GROWTH = "Tăng trưởng doanh thu thuần của HPG từ năm 2023 đến năm 2024 là bao nhiêu %?"
Q_DIFF = "Chênh lệch doanh thu thuần của HPG năm 2024 so với năm 2023 là bao nhiêu tỷ đồng?"
Q_ENTITY_DIFF = "Hiệu số vốn chủ sở hữu của công ty mẹ Tổng Công ty Khí Việt Nam - CTCP và công ty mẹ Tổng Công ty Điện lực Dầu khí Việt Nam tính đến ngày 31/12/2023 là bao nhiêu tỷ đồng?"
Q_AVG = "Trung bình doanh thu thuần của HPG trong các năm 2022, 2023 và 2024 là bao nhiêu tỷ đồng?"
Q_FINANCIAL_INCOME_AVG = "Tổng doanh thu hoạt động tài chính trung bình của Tổng Công ty cổ phần Phát triển Khu Công nghiệp công ty mẹ trong các năm 2018, 2019, 2020, 2021 và 2022 là mấy trăm tỷ đồng?"
Q_DETAIL_DIFF = "Chênh lệch giá trị hàng tồn kho - Nguyên vật liệu giữa (giá gốc) cuối năm 2023 và cuối năm 2022 của PC1 là bao nhiêu tỷ đồng?"
Q_NOTE_ENTITY_DIFF = "Tính chênh lệch quy mô dư nợ cho vay khách hàng nội địa của công ty mẹ Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh so với công ty mẹ Ngân hàng TMCP An Bình vào năm 2021 theo đơn vị triệu đồng."
Q_INTEREST_PAYABLE_DETAIL = "Hiệu số giữa Chi phí lãi vay phải trả ngắn hạn của công ty mẹ KBC cuối năm 2019 và cuối năm 2016 là bao nhiêu tỷ đồng?"
Q_VENDOR_PAYABLE_DETAIL = "Hiệu số số dư nợ phải trả người bán ngắn hạn giữa CTCP Hàng không Vietjet và CTCP Container Việt Nam đến ngày 31/12/2016 là bao nhiêu tỷ đồng?"
Q_COLLATERAL_GROWTH = "Tổng tài sản, GTCG nhận thế chấp, cầm cố và chiết khấu, tái chiết khấu của ACB tăng bao nhiêu phần trăm từ cuối năm 2022 đến cuối năm 2025?"
Q_NET_MARGIN = "Tỷ suất lợi nhuận ròng của HBC năm 2016 là bao nhiêu %?"
Q_ROA = "ROA của CEO năm 2016 là bao nhiêu phần trăm?"
Q_NP_ASSETS = "Lợi nhuận sau thuế trên tổng tài sản cuối năm 2016 của CEO là bao nhiêu phần trăm?"
Q_DEBT_ASSETS = "Tỷ lệ nợ trên tổng tài sản của công ty mẹ SGB cuối năm 2015 là bao nhiêu phần trăm?"
Q_CL_EQUITY = "Tính tỷ số nợ ngắn hạn trên vốn chủ sở hữu của công ty mẹ VNM năm 2022."
Q_COGS_REVENUE = "Tỷ lệ giá vốn hàng bán trên doanh thu thuần của HPG năm 2024 là bao nhiêu %?"
Q_CFO_PBT = "Tỷ lệ dòng tiền thuần từ hoạt động kinh doanh trên lợi nhuận trước thuế của công ty mẹ Ngân hàng TMCP Quốc Dân năm 2016 là bao nhiêu %?"
Q_SELECTION = (
    "Trong các năm 2020-2024, năm có doanh thu thuần cao nhất của HPG có hệ số "
    "thanh toán hiện hành là bao nhiêu lần?"
)


state = {
    "question": Q_RATIO,
    "tickers": ["HPG"],
    "years": [2024],
    "doc_type": "consolidated",
    "metric": "",
}
check("formula cue attempts the branch", should_attempt_formula_facts(state)[0])
check(
    "missing scope does not attempt",
    not should_attempt_formula_facts({**state, "tickers": []})[0],
)
check(
    "selection marker is gated before planning",
    not should_attempt_formula_facts({**state, "question": Q_SELECTION, "years": [2020, 2021, 2022, 2023, 2024]})[0],
)
check(
    "formula cue without a catalog metric anchor falls back",
    not should_attempt_formula_facts({
        **state,
        "question": "Tăng trưởng khoản vay ngắn hạn của MCH từ cuối năm 2021 đến cuối năm 2023 là bao nhiêu %?",
        "metric": "",
    })[0],
)
check(
    "segment formula is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": "Tốc độ tăng trưởng doanh thu thuần từ hoạt động xây dựng của DIG tính từ năm 2022 lên 2023 là bao nhiêu %?",
        "years": [2022, 2023],
    })[0],
)
check(
    "borrowings ratio is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": "Tỷ số nợ vay trên tổng tài sản của công ty mẹ HAG năm 2022 là bao nhiêu phần trăm?",
        "years": [2022],
    })[0],
)
check(
    "note detail inventory diff is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": Q_DETAIL_DIFF,
        "tickers": ["PC1"],
        "years": [2022, 2023],
    })[0],
)
check(
    "bank loan-note entity diff is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": Q_NOTE_ENTITY_DIFF,
        "tickers": ["HDB", "ABB"],
        "years": [2021],
        "doc_type": "separate",
    })[0],
)
check(
    "interest payable detail diff is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": Q_INTEREST_PAYABLE_DETAIL,
        "tickers": ["KBC"],
        "years": [2016, 2019],
        "doc_type": "separate",
    })[0],
)
check(
    "vendor payable detail diff is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": Q_VENDOR_PAYABLE_DETAIL,
        "tickers": ["VJC", "VSC"],
        "years": [2016],
        "doc_type": "unknown",
    })[0],
)
check(
    "collateral detail growth is rejected before planning",
    not should_attempt_formula_facts({
        **state,
        "question": Q_COLLATERAL_GROWTH,
        "tickers": ["ACB"],
        "years": [2022, 2025],
    })[0],
)


ratio = FormulaSupportedPlan(
    operation="ratio",
    tickers=["HPG"],
    years=[2024],
    doc_type="consolidated",
    answer_metric="current_ratio",
    target_unit="ratio",
).to_structured_plan()
check("direct ratio plan is supported", supported_formula_plan(ratio, Q_RATIO)[0])
got = execute_formula_plan(ratio, question=Q_RATIO)["answer"]
expected = execute_plan(ratio, question=Q_RATIO)["answer"]
check("direct ratio executes through fact layer", close(got, expected))
det = deterministic_formula_plan({**state, "question": Q_RATIO, "unit_hint": "lần"})
check("deterministic Type 2 ratio is planned without LLM", det.supported and det.answer_metric == "current_ratio")
got = execute_formula_plan(det, question=Q_RATIO, unit_hint="lần")["answer"]
expected = execute_plan(det, question=Q_RATIO, unit_hint="lần")["answer"]
check("deterministic Type 2 ratio executes", close(got, expected))


net_margin = StructuredPlan(
    operation="ratio",
    tickers=["HBC"],
    years=[2016],
    doc_type="unknown",
    answer_metric="net_margin",
    target_unit="percent",
)
check("net margin alias is anchored", supported_formula_plan(net_margin, Q_NET_MARGIN)[0])
det = deterministic_formula_plan({
    **state,
    "question": Q_NET_MARGIN,
    "tickers": ["HBC"],
    "years": [2016],
    "doc_type": "unknown",
    "unit_hint": "%",
})
check("deterministic net margin chooses derived ratio", det.supported and det.answer_metric == "net_margin")

for name, question, metric, ticker, year in [
    ("roa", Q_ROA, "roa", "CEO", 2016),
    ("net profit/assets", Q_NP_ASSETS, "net_profit_to_total_assets", "CEO", 2016),
    ("debt/assets", Q_DEBT_ASSETS, "debt_to_assets", "SGB", 2015),
    ("current liabilities/equity", Q_CL_EQUITY, "current_liabilities_to_equity", "VNM", 2022),
    ("cogs/revenue", Q_COGS_REVENUE, "cogs_to_revenue", "HPG", 2024),
    ("cfo/pbt", Q_CFO_PBT, "cfo_to_profit_before_tax", "NVB", 2016),
]:
    plan = deterministic_formula_plan({
        **state,
        "question": question,
        "tickers": [ticker],
        "years": [year],
        "doc_type": "unknown",
        "unit_hint": "%" if name != "current liabilities/equity" else "lần",
    })
    check(f"deterministic Type 2 maps {name}", plan.supported and plan.answer_metric == metric)


growth = StructuredPlan(
    operation="growth",
    tickers=["HPG"],
    years=[2023, 2024],
    doc_type="consolidated",
    answer_metric="net_revenue",
    target_unit="percent",
)
check("growth plan is supported", supported_formula_plan(growth, Q_GROWTH)[0])
det_growth = deterministic_formula_plan({
        **state,
        "question": Q_GROWTH,
        "tickers": ["HPG"],
        "years": [2023, 2024],
        "doc_type": "consolidated",
        "unit_hint": "%",
})
check("deterministic Type 3 planner maps simple growth", det_growth.supported and det_growth.answer_metric == "net_revenue")
got = execute_formula_plan(growth, question=Q_GROWTH)["answer"]
expected = execute_plan(growth, question=Q_GROWTH)["answer"]
check("growth executes and scales to percent", close(got, expected))
got = execute_formula_plan(det_growth, question=Q_GROWTH, unit_hint="%")["answer"]
check("deterministic Type 3 growth executes", close(got, expected))


diff = StructuredPlan(
    operation="diff",
    tickers=["HPG"],
    years=[2023, 2024],
    doc_type="consolidated",
    answer_metric="net_revenue",
    target_unit="billion_vnd",
)
check("period diff plan is supported", supported_formula_plan(diff, Q_DIFF)[0])
det_diff = deterministic_formula_plan({
    **state,
    "question": Q_DIFF,
    "tickers": ["HPG"],
    "years": [2023, 2024],
    "doc_type": "consolidated",
    "unit_hint": "tỷ",
})
check("deterministic Type 3 planner maps simple period diff", det_diff.supported and det_diff.answer_metric == "net_revenue")
got = execute_formula_plan(diff, question=Q_DIFF)["answer"]
expected = execute_plan(diff, question=Q_DIFF)["answer"]
check("period diff executes through fact layer", close(got, expected))
got = execute_formula_plan(det_diff, question=Q_DIFF, unit_hint="tỷ")["answer"]
check("deterministic Type 3 period diff executes", close(got, expected))


entity_diff = StructuredPlan(
    operation="diff",
    tickers=["GAS", "POW"],
    years=[2023],
    doc_type="separate",
    answer_metric="equity",
    target_unit="billion_vnd",
)
check("multi-entity main-statement diff plan is supported", supported_formula_plan(entity_diff, Q_ENTITY_DIFF)[0])
det_entity_diff = deterministic_formula_plan({
    **state,
    "question": Q_ENTITY_DIFF,
    "tickers": ["GAS", "POW"],
    "years": [2023],
    "doc_type": "separate",
    "unit_hint": "tỷ",
})
check(
    "deterministic Type 4 planner maps simple entity diff",
    det_entity_diff.supported
    and det_entity_diff.operation == "diff"
    and det_entity_diff.tickers == ["GAS", "POW"]
    and det_entity_diff.answer_metric == "equity",
)
got = execute_formula_plan(det_entity_diff, question=Q_ENTITY_DIFF, unit_hint="tỷ")["answer"]
expected = execute_plan(entity_diff, question=Q_ENTITY_DIFF)["answer"]
check("deterministic entity diff executes with resolved ticker order", close(got, expected))


avg = StructuredPlan(
    operation="avg",
    tickers=["HPG"],
    years=[2022, 2023, 2024],
    doc_type="consolidated",
    answer_metric="net_revenue",
    target_unit="billion_vnd",
)
check("average plan is supported", supported_formula_plan(avg, Q_AVG)[0])
det_avg = deterministic_formula_plan({
        **state,
        "question": Q_AVG,
        "tickers": ["HPG"],
        "years": [2022, 2023, 2024],
        "doc_type": "consolidated",
        "unit_hint": "tỷ",
})
check(
    "deterministic Type 3 planner maps simple average",
    det_avg.supported and det_avg.operation == "avg" and det_avg.answer_metric == "net_revenue",
)
got = execute_formula_plan(avg, question=Q_AVG)["answer"]
expected = execute_plan(avg, question=Q_AVG)["answer"]
check("average executes through fact layer", close(got, expected))
got = execute_formula_plan(det_avg, question=Q_AVG, unit_hint="tỷ")["answer"]
check("deterministic Type 3 average executes", close(got, expected))

det_financial_income_avg = deterministic_formula_plan({
    **state,
    "question": Q_FINANCIAL_INCOME_AVG,
    "tickers": ["SNZ"],
    "years": [2018, 2019, 2020, 2021, 2022],
    "doc_type": "separate",
    "unit_hint": "trăm tỷ",
})
check(
    "financial income average is catalogued",
    det_financial_income_avg.supported
    and det_financial_income_avg.operation == "avg"
    and det_financial_income_avg.answer_metric == "financial_income",
)
got = execute_formula_plan(
    det_financial_income_avg,
    question=Q_FINANCIAL_INCOME_AVG,
    unit_hint="trăm tỷ",
)["answer"]
check("financial income average matches q820 gold", close(got, 4.069))


bad_ratio_scope = StructuredPlan(
    operation="ratio",
    tickers=["HPG"],
    years=[2023, 2024],
    doc_type="consolidated",
    answer_metric="current_ratio",
)
check(
    "ratio rejects multi-year scope",
    not supported_formula_plan(bad_ratio_scope, "current ratio HPG 2023-2024")[0],
)
check(
    "money target rejects ratio answer",
    not supported_formula_plan(
        StructuredPlan(
            operation="ratio",
            tickers=["HPG"],
            years=[2024],
            doc_type="consolidated",
            answer_metric="current_ratio",
            target_unit="billion_vnd",
        ),
        "current ratio HPG",
    )[0],
)
check(
    "selection text rejects otherwise valid metric plan",
    not supported_formula_plan(ratio, Q_SELECTION)[0],
)
check(
    "planner cannot swap an unanchored metric into a growth question",
    not supported_formula_plan(
        StructuredPlan(
            operation="growth",
            tickers=["MCH"],
            years=[2021, 2023],
            doc_type="unknown",
            answer_metric="liabilities",
            target_unit="percent",
        ),
        "Tăng trưởng khoản vay ngắn hạn của MCH từ cuối năm 2021 đến cuối năm 2023 là bao nhiêu %?",
    )[0],
)
check(
    "segment revenue growth falls back to raw-table codegen",
    not supported_formula_plan(
        StructuredPlan(
            operation="growth",
            tickers=["DIG"],
            years=[2022, 2023],
            doc_type="unknown",
            answer_metric="net_revenue",
            target_unit="percent",
        ),
        "Tốc độ tăng trưởng doanh thu thuần từ hoạt động xây dựng của DIG tính từ năm 2022 lên 2023 là bao nhiêu %?",
    )[0],
)
check(
    "borrowings do not degrade to liabilities ratios",
    not supported_formula_plan(
        StructuredPlan(
            operation="ratio",
            tickers=["HAG"],
            years=[2022],
            doc_type="separate",
            answer_metric="debt_to_assets",
            target_unit="percent",
        ),
        "Tỷ số nợ vay trên tổng tài sản của công ty mẹ HAG năm 2022 là bao nhiêu phần trăm?",
    )[0],
)
check(
    "unsupported primitive ratio is not guessed",
    not deterministic_formula_plan({
        **state,
        "question": "Tỷ lệ chi phí bán hàng trên doanh thu thuần của HPG năm 2024 là bao nhiêu %?",
        "tickers": ["HPG"],
        "years": [2024],
        "doc_type": "unknown",
        "unit_hint": "%",
    }).supported,
)

print("tất cả PASS")
