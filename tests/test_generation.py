"""Regression tests for planner orchestration contracts (no LLM calls)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.planning.repairs import (
    repair_plan_order,
    repair_plan_output_unit,
    repair_non_numeric_bindings,
    repair_prior_year_coverage,
    repair_select_answer_periods,
)
from finance_qa.planning.validators import (
    binding_concept_errors,
    plan_contract_errors,
    plan_order_errors,
    semantic_errors,
)
from finance_qa.preprocessing.questions import detect_unit


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def binding(binding_id: str, variable: str, year: int) -> dict:
    return {
        "id": binding_id,
        "variable": variable,
        "row_index": 0,
        "column": str(year),
        "source_unit": "vnd",
        "meaning": f"value {year}",
    }


q752 = (
    "Chênh lệch lãi thuần từ hoạt động dịch vụ giữa Ngân hàng TMCP An Bình "
    "và Ngân hàng TMCP Quân đội năm 2022 là bao nhiêu triệu đồng?"
)
reversed_difference = {
    "bindings": [binding("abb", "df1", 2022), binding("mbb", "df2", 2022)],
    "formula": "mbb - abb",
    "output_unit": "million_vnd",
}
table_ids = {
    "df1": "ABB_financial_statements_2022_consolidated|1",
    "df2": "MBB_financial_statements_2022_consolidated|1",
}
check(
    "reversed company subtraction rejected",
    len(plan_order_errors(q752, reversed_difference, table_ids)) == 1,
)
ordered, change = repair_plan_order(q752, reversed_difference, table_ids)
check(
    "reversed company subtraction repaired",
    ordered["formula"] == "abb - mbb"
    and change is not None
    and not plan_order_errors(q752, ordered, table_ids),
)

q363 = (
    "Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, hệ số "
    "khả năng thanh toán lãi vay là bao nhiêu lần?"
)
incomplete_nested = {
    "bindings": [
        binding("de_2016", "df1", 2016),
        binding("de_2018", "df1", 2018),
        binding("de_2020", "df1", 2020),
    ],
    "formula": "argmax({'2016': de_2016, '2018': de_2018, '2020': de_2020})",
    "output_unit": "year",
}
contract_errors = plan_contract_errors(q363, incomplete_nested)
check("answer unit contract enforced", any("output_unit" in e for e in contract_errors))
check(
    "all requested years must be covered",
    any("2017" in e and "2019" in e for e in contract_errors),
)

# Unit extraction is shared metadata, not a question-specific planner rule.
check(
    "ratio word is not billion currency",
    detect_unit("Tỷ số D/E cao nhất có hệ số thanh toán lãi vay bao nhiêu lần?") == "lần",
)
check(
    "percentage output outranks tỷ lệ wording",
    detect_unit("Chênh lệch tỷ lệ này là bao nhiêu điểm phần trăm?") == "phần trăm",
)
check(
    "long money unit beats nested suffix",
    detect_unit("Giá trị là mấy nghìn tỷ đồng?") == "nghìn tỷ",
)
check(
    "entity count outranks ratio thresholds",
    detect_unit("Có bao nhiêu doanh nghiệp có hệ số trên 1 lần?") == "count",
)

q380 = (
    "Trong nhóm thử nghiệm, có bao nhiêu doanh nghiệp có hệ số thanh toán "
    "nhanh trên 1 lần?"
)
count_errors = plan_contract_errors(
    q380,
    {
        "bindings": [binding("x", "df1", 2024)],
        "formula": "count_true([x > 1])",
        "output_unit": "ratio",
    },
)
check("entity-count output contract enforced", any("output_unit" in e for e in count_errors))

wrong_period = {
    "bindings": [
        {
            **binding("interest_expense_2016", "df7", 2016),
            "column": "Năm nay",
            "meaning": "Chi phí lãi vay năm 2016",
        }
    ],
    "formula": "interest_expense_2016",
    "output_unit": "vnd",
}
period_errors = plan_contract_errors(
    "Chi phí lãi vay năm 2016 là bao nhiêu đồng?",
    wrong_period,
    {"df7": "KBC_financial_statements_2020_consolidated|9"},
)
check(
    "binding year must match report column period",
    any("biểu diễn năm 2020" in error for error in period_errors),
)

check(
    "nested multi-year shortcut rejected",
    any(
        "phép chọn max" in error
        for error in semantic_errors(q363, "df1.iloc[0]['2020']", {})
    ),
)
check(
    "nested multi-year selection accepted",
    not semantic_errors(
        q363,
        "pd.Series([df1.iloc[0]['2019'], df1.iloc[0]['2020']]).idxmax()",
        {},
    ),
)

share_capital_frame = {
    "df1": pd.DataFrame(
        {
            "Chỉ tiêu": [
                "D. VỐN CHỦ SỞ HỮU",
                "1.1. Vốn góp của chủ sở hữu",
                "a. Cổ phiếu phổ thông có quyền biểu quyết",
                "1.2. Thặng dư vốn cổ phần",
            ],
            "Số cuối năm": [2202.0, 1322.0, 1322.0, 81.0],
        }
    )
}
wrong_share_capital = {
    "bindings": [
        {
            **binding("share_capital", "df1", 2020),
            "row_index": 0,
            "column": "Số cuối năm",
            "meaning": "Tổng vốn chủ sở hữu cuối năm 2020",
        }
    ],
    "formula": "share_capital",
    "output_unit": "trillion_vnd",
}
concept_errors = binding_concept_errors(
    "Vốn cổ phần cuối năm 2020 là bao nhiêu?",
    wrong_share_capital,
    share_capital_frame,
)
check(
    "share capital cannot bind total equity",
    len(concept_errors) == 1 and "row 1" in concept_errors[0],
)
right_share_capital = {
    **wrong_share_capital,
    "bindings": [{**wrong_share_capital["bindings"][0], "row_index": 1}],
}
check(
    "owner contributed capital satisfies share-capital concept",
    not binding_concept_errors(
        "Vốn cổ phần cuối năm 2020 là bao nhiêu?",
        right_share_capital,
        share_capital_frame,
    ),
)
domestic_plan = {
    **wrong_share_capital,
    "bindings": [
        {
            **wrong_share_capital["bindings"][0],
            "meaning": "Cho vay các tổ chức kinh tế, cá nhân nước ngoài năm 2020",
        }
    ],
}
check(
    "domestic question rejects foreign row meaning",
    any(
        "mâu thuẫn" in error
        for error in binding_concept_errors(
            "Cho vay các tổ chức kinh tế và cá nhân trong nước năm 2020",
            domestic_plan,
            share_capital_frame,
        )
    ),
)

interest_frames = {
    "df1": pd.DataFrame(
        {
            "Mã số": [23, 50, 61],
            "Chỉ tiêu": [
                "Chi phí lãi vay",
                "Tổng lợi nhuận kế toán trước thuế",
                "Lợi nhuận sau thuế của công ty mẹ",
            ],
            "2020": [-20.0, 40.0, 22.0],
        }
    )
}
wrong_interest_plan = {
    "bindings": [
        {**binding("interest_2020", "df1", 2020), "row_index": 0},
        {**binding("profit_2020", "df1", 2020), "row_index": 2},
    ],
    "formula": "(profit_2020 + abs(interest_2020)) / abs(interest_2020)",
    "output_unit": "ratio",
}
check(
    "interest coverage requires pre-tax profit component",
    any(
        "lợi nhuận trước thuế" in error
        for error in binding_concept_errors(
            "Hệ số khả năng thanh toán lãi vay là bao nhiêu lần?",
            wrong_interest_plan,
            interest_frames,
        )
    ),
)
unit_repaired, unit_change = repair_plan_output_unit(
    "Vốn cổ phần cuối năm 2020 là bao nhiêu nghìn tỷ đồng?",
    {**right_share_capital, "output_unit": "billion_vnd"},
)
check(
    "unambiguous question unit repairs planner output unit",
    unit_repaired["output_unit"] == "trillion_vnd" and unit_change is not None,
)

prior_frames = {
    "df2018": pd.DataFrame(
        {
            "label": ["Nợ phải trả", "Vốn chủ sở hữu"],
            "Số cuối năm": [80.0, 100.0],
            "Số đầu năm": [70.0, 100.0],
        }
    ),
    "df2020": pd.DataFrame(
        {
            "label": ["Nợ phải trả", "Vốn chủ sở hữu", "Kết quả"],
            "Số cuối năm": [120.0, 100.0, 3.3],
            "Số đầu năm": [90.0, 100.0, 2.0],
        }
    ),
}
prior_plan = {
    "bindings": [
        {**binding("debt_2018", "df2018", 2018), "row_index": 0, "column": "Số cuối năm"},
        {**binding("equity_2018", "df2018", 2018), "row_index": 1, "column": "Số cuối năm"},
        {**binding("debt_2020", "df2020", 2020), "row_index": 0, "column": "Số cuối năm"},
        {**binding("equity_2020", "df2020", 2020), "row_index": 1, "column": "Số cuối năm"},
        {**binding("answer_2020", "df2020", 2020), "row_index": 2, "column": "Số cuối năm"},
    ],
    "formula": (
        "select(argmax({'2018': debt_2018 / equity_2018, "
        "'2020': debt_2020 / equity_2020}), {'2020': answer_2020})"
    ),
    "output_unit": "ratio",
}
prior_repaired, prior_changes = repair_prior_year_coverage(
    "Trong các năm 2017, 2018, 2019, 2020, lấy kết quả tại năm D/E cao nhất",
    prior_plan,
    prior_frames,
)
check(
    "missing rank years expand from comparative columns",
    all(f"'{year}'" in prior_repaired["formula"] for year in (2017, 2018, 2019, 2020))
    and {b["column"] for b in prior_repaired["bindings"] if b["id"].endswith(("2017", "2019"))}
    == {"Số đầu năm"}
    and len(prior_changes) == 1,
)

period_mismatch_plan = {
    **prior_plan,
    "bindings": [
        *prior_plan["bindings"],
        {
            **binding("answer_2021", "df2020", 2021),
            "row_index": 2,
            "column": "Số cuối năm",
        },
    ],
    "formula": (
        "select(argmax({'2018': debt_2018 / equity_2018, "
        "'2020': debt_2020 / equity_2020}), "
        "{'2020': answer_2020, '2021': answer_2021})"
    ),
}
period_repaired, period_changes = repair_select_answer_periods(
    period_mismatch_plan,
    {
        "df2018": "AAA_financial_statements_2018_consolidated|1",
        "df2020": "AAA_financial_statements_2020_consolidated|1",
    },
)
check(
    "select branch follows actual report period, not claimed year",
    period_repaired["formula"].count("'2021'") == 0 and len(period_changes) == 1,
)

ocr_frames = {
    "df2021": pd.DataFrame(
        {
            "label": ["Cho vay các tổ chức kinh tế và cá nhân trong nước"],
            "Số dư cuối năm": ["101.578.366.954.676277.259.041.753"],
        }
    ),
    "df2022": pd.DataFrame(
        {
            "label": ["Cho vay các tổ chức kinh tế và cá nhân trong nước"],
            "Số dư cuối năm": [119_510.0],
            "Số dư đầu năm": [101_578.0],
        }
    ),
}
ocr_plan = {
    "bindings": [
        {
            **binding("domestic_loans_2021", "df2021", 2021),
            "column": "Số dư cuối năm",
            "meaning": "Cho vay các tổ chức kinh tế và cá nhân trong nước năm 2021",
        }
    ],
    "formula": "domestic_loans_2021",
    "output_unit": "vnd",
}
ocr_repaired, ocr_changes = repair_non_numeric_bindings(
    ocr_plan,
    ocr_frames,
    {
        "df2021": "OCB_financial_statements_2021_consolidated|1",
        "df2022": "OCB_financial_statements_2022_consolidated|1",
    },
)
check(
    "non-numeric OCR binding uses unique next-report prior period",
    ocr_repaired["bindings"][0]["variable"] == "df2022"
    and ocr_repaired["bindings"][0]["column"] == "Số dư đầu năm"
    and len(ocr_changes) == 1,
)

print("tất cả PASS")
