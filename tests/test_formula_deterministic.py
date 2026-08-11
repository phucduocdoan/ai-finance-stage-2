"""Regression tests for deterministic canonical formula execution (no LLM calls)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pandas as pd
from pydantic import ValidationError

from finance_qa.modules.tools.metrics import execute_canonical_plan
from finance_qa.modules.codegen.formula import (
    CanonicalPlan,
    _execute_nested_selection,
    _prefers_fact_plan,
    _postprocess_formula_answer,
)
from finance_qa.modules.data.canonical import canonical_frame


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


data = {
    "KBC": {
        "2019": {
            "total_debt": 60.0,
            "equity": 100.0,
            "profit_before_tax": 20.0,
            "interest_expense": -5.0,
        },
        "2020": {
            "total_debt": 130.0,
            "equity": 100.0,
            "profit_before_tax": 30.0,
            "interest_expense": -10.0,
        },
    }
}

q363 = (
    "Trong giai đoạn 2019-2020, vào năm KBC có tỷ số D/E cao nhất, "
    "hệ số khả năng thanh toán lãi vay là bao nhiêu lần?"
)
answer = _execute_nested_selection(data, [2019, 2020], "de_ratio", "max", "icr")
check("D/E argmax then ICR", answer is not None and answer[0] == 4.0)
check("query records deterministic path", answer is not None and "select=de_ratio.max" in answer[1])


hpg = {
    "HPG": {
        "2020": {
            "net_revenue": 90.0,
            "current_assets": 50.0,
            "short_term_debt": 25.0,
        },
        "2021": {
            "net_revenue": 150.0,
            "current_assets": 120.0,
            "short_term_debt": 80.0,
        },
    }
}

q415 = (
    "Tại năm mà Hoà Phát đạt doanh thu thuần cao nhất trong giai đoạn "
    "2020-2021, hệ số thanh toán hiện hành cuối năm là bao nhiêu lần?"
)
answer = _execute_nested_selection(hpg, [2020, 2021], "net_revenue", "max", "current_ratio")
check("net revenue argmax then current ratio", answer is not None and answer[0] == 1.5)


outside = _execute_nested_selection(hpg, [2020], "net_revenue", "max", "current_ratio")
check("year filter is respected", outside is not None and outside[0] == 2.0)


unsupported = _execute_nested_selection(hpg, [2021], "unsupported", "max", "current_ratio")
check("unsupported metric falls back to LLM path", unsupported is None)


vre = {
    "VRE": {
        "2021": {"current_assets": 300.0, "inventory": 84.0, "short_term_debt": 100.0},
        "2022": {"current_assets": 260.0, "inventory": 99.0, "short_term_debt": 100.0},
        "2023": {"current_assets": 255.0, "inventory": 104.53, "short_term_debt": 100.0},
        "2024": {
            "current_assets": 270.0,
            "inventory": 67.03,
            "short_term_debt": 100.0,
            "net_cash_operating": 12.804306843148647,
        },
    }
}
plan = {
    "universe": {"tickers": ["VRE"], "years": [2021, 2022, 2023, 2024]},
    "select": {"metric": "quick_ratio", "direction": "min", "offset_years": 1},
    "answer": {"metric": "cfo_to_short_term_debt", "unit": "lần"},
}
answer = execute_canonical_plan(vre, plan)
check("offset year after selected year", answer is not None and abs(answer[0] - 0.12804306843148647) < 1e-12)


hpg_extended = {
    "HPG": {
        "2018": {"gross_profit": 20.90, "net_revenue": 100.0, "net_cash_operating": 8.0, "net_profit": 10.0, "owners_equity": 80.0},
        "2019": {"gross_profit": 17.57, "net_revenue": 100.0, "net_cash_operating": 9.0, "net_profit": 10.0, "owners_equity": 85.0},
        "2020": {"gross_profit": 20.98, "net_revenue": 100.0, "net_cash_operating": 7.0, "net_profit": 10.0, "owners_equity": 90.0},
        "2021": {"gross_profit": 27.46, "net_revenue": 100.0, "net_cash_operating": 6.0, "net_profit": 10.0, "owners_equity": 100.0},
        "2022": {"gross_profit": 11.85, "net_revenue": 100.0, "net_cash_operating": 15.0, "net_profit": 10.0, "owners_equity": 100.0},
        "2023": {"gross_profit": 10.88, "net_revenue": 100.0, "net_cash_operating": 13.0, "net_profit": 10.0, "owners_equity": 110.0},
        "2024": {"gross_profit": 13.32, "net_revenue": 100.0, "net_cash_operating": 12.0, "net_profit": 10.0, "owners_equity": 120.0},
    }
}
plan = {
    "universe": {"tickers": ["HPG"], "years": list(range(2018, 2025))},
    "filters": [{"metric": "gross_margin", "op": "below_median"}],
    "select": {"metric": "cash_ratio", "direction": "max"},
    "answer": {"metric": "roe", "unit": "phần trăm"},
}
answer = execute_canonical_plan(hpg_extended, plan)
check("median filter then max selector then percent unit", answer is not None and abs(answer[0] - 10.0) < 1e-12)


money = {
    "AAA": {
        "2024": {"net_revenue": 2_500_000_000_000.0},
    }
}
answer = execute_canonical_plan(
    money,
    {"universe": {"tickers": ["AAA"], "years": [2024]}, "answer": {"metric": "net_revenue", "unit": "tỷ đồng"}},
)
check("money unit conversion", answer is not None and answer[0] == 2500.0)

multi = {
    "HSG": {"2024": {"current_assets": 100.0, "inventory": 40.0, "short_term_debt": 100.0}},
    "NKG": {"2024": {"current_assets": 100.0, "inventory": 5_000_000_000_000.0, "short_term_debt": 200.0}},
}
answer = execute_canonical_plan(
    multi,
    {
        "universe": {"tickers": ["HSG", "NKM"], "years": [2024]},
        "select": {"metric": "quick_ratio", "direction": "min"},
        "answer": {"metric": "inventory", "unit": "nghìn tỷ đồng"},
    },
    default_tickers=["HSG", "NKG"],
)
check("authoritative default tickers override hallucinated plan tickers", answer is not None and answer[0] == 5.0)

years_override = {
    "HPG": {
        "2021": {"net_cash_operating": 10.0, "net_profit": 10.0, "profit_before_tax": 10.0, "interest_expense": -5.0},
        "2024": {"net_cash_operating": 1.0, "net_profit": 10.0, "profit_before_tax": 30.0, "interest_expense": -10.0},
    }
}
answer = execute_canonical_plan(
    years_override,
    {
        "universe": {"tickers": ["HPG"], "years": [2021]},
        "filters": [{"metric": "net_profit", "op": ">", "value": 0}],
        "select": {"metric": "cfo_to_net_profit", "direction": "min"},
        "answer": {"metric": "icr", "unit": "lần"},
    },
    default_years=[2021, 2024],
)
check("authoritative default years override omitted plan years", answer is not None and answer[0] == 4.0)

fpt = {"FPT": {"2022": {"net_profit": 6_491_000_000_000.0, "net_cash_operating": 5_054_000_000_000.0}}}
answer = execute_canonical_plan(
    fpt,
    {"universe": {"tickers": ["FPT"], "years": [2022]}, "answer": {"metric": "net_profit_minus_cfo", "unit": "nghìn tỷ đồng"}},
)
check("net profit not converted to CFO metric", answer is not None and answer[0] == 1.437)


shifted_cf = pd.DataFrame(
    [
        {
            "Unnamed: 0": "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
            "CHỈ TIÊU": "20",
            "Mã số": 758109.0,
            "Năm nay": 3892009.0,
            "Năm trước": None,
        }
    ]
)
canon = canonical_frame(shifted_cf, "VRE_financial_statements_2024_consolidated|7", "cash_flow")
check("shifted cash-flow mã số row is canonicalized", canon == {"net_cash_operating": {2024: 758109.0, 2023: 3892009.0}})

valid_plan = CanonicalPlan.model_validate(
    {
        "median_filter_mentioned": True,
        "universe": {"tickers": ["HPG"], "years": [2024]},
        "filters": [{"metric": "gross_margin", "op": "below_median"}],
        "select": {"metric": "cash_ratio", "direction": "max"},
        "answer": {"metric": "roe", "unit": "phần trăm"},
    }
)
check("pydantic accepts a consistent canonical plan", valid_plan.answer is not None and valid_plan.answer.metric == "roe")

try:
    CanonicalPlan.model_validate(
        {
            "filters": [{"metric": "gross_margin", "op": "below_median"}],
            "answer": {"metric": "roe"},
        }
    )
    median_rejected = False
except ValidationError:
    median_rejected = True
check("pydantic rejects median filter without median flag", median_rejected)

try:
    CanonicalPlan.model_validate(
        {
            "year_offset_reference": "none",
            "select": {"metric": "quick_ratio", "direction": "min", "offset_years": 1},
            "answer": {"metric": "cfo_to_short_term_debt"},
        }
    )
    offset_rejected = False
except ValidationError:
    offset_rejected = True
check("pydantic rejects inconsistent year offset", offset_rejected)

check(
    "one-shot raw VND answer converts to requested money unit",
    _postprocess_formula_answer("Hàng tồn kho là bao nhiêu nghìn tỷ đồng?", 6_690_482_934_519.0) == 6.690482934519,
)
check(
    "one-shot already-converted money answer is left alone",
    _postprocess_formula_answer("Hàng tồn kho là bao nhiêu nghìn tỷ đồng?", 6.690482934519) == 6.690482934519,
)
check(
    "unit_hint none falls back to question text",
    _postprocess_formula_answer("Hàng tồn kho là bao nhiêu nghìn tỷ đồng?", 6_690_482_934_519.0, "none") == 6.690482934519,
)
check(
    "plain median rank stays on canonical path first",
    not _prefers_fact_plan("ROE tại năm có CFO/doanh thu cao nhất trong các năm dưới trung vị là bao nhiêu phần trăm?"),
)
check(
    "aggregate questions prefer fact plan",
    _prefers_fact_plan("biên lợi nhuận ròng bình quân của các doanh nghiệp là bao nhiêu phần trăm?"),
)
check(
    "scenario questions prefer fact plan",
    _prefers_fact_plan("nếu EBIT proxy giảm 15% thì ICR thấp nhất là bao nhiêu lần?"),
)
