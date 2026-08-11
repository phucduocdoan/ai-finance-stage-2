"""Tests for typed fact-plan deterministic execution."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.codegen.fact_plan import FactPlan, execute_fact_plan


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


quick_ratio_data = {
    "AAA": {
        "2024": {
            "current_assets": 100.0,
            "inventory": 20.0,
            "short_term_debt": 100.0,
            "net_cash_operating": 30.0,
            "net_profit": 30.0,
        }
    },
    "BBB": {
        "2024": {
            "current_assets": 90.0,
            "inventory": 30.0,
            "short_term_debt": 100.0,
            "net_cash_operating": 80.0,
            "net_profit": 40.0,
        }
    },
}
answer = execute_fact_plan(
    quick_ratio_data,
    {
        "universe": {"tickers": ["AAA", "BBB"], "years": [2024]},
        "select": {"metric": "cfo_to_net_profit", "direction": "max"},
        "answer": {"metric": "quick_ratio", "unit": "lần", "aggregate": "mean"},
    },
)
check("select by CFO/LNST then answer quick ratio", answer is not None and answer[0] == 0.6)
check("selected-row answer overrides stray aggregate", answer is not None and ".mean" not in answer[1])
check("query records fact-plan path", answer is not None and "fact_plan(" in answer[1])


aggregate_data = {
    "A": {"2024": {"inventory": 10.0, "total_assets": 100.0, "net_profit": 8.0, "net_revenue": 100.0}},
    "B": {"2024": {"inventory": 50.0, "total_assets": 100.0, "net_profit": 12.0, "net_revenue": 100.0}},
    "D": {"2024": {"inventory": 70.0, "total_assets": 100.0, "net_profit": 16.0, "net_revenue": 100.0}},
    "C": {"2024": {"inventory": 90.0, "total_assets": 100.0, "net_profit": 24.0, "net_revenue": 100.0}},
}
answer = execute_fact_plan(
    aggregate_data,
    {
        "median_filter_mentioned": True,
        "universe": {"tickers": ["A", "B", "C", "D"], "years": [2024]},
        "filters": [{"metric": "inventory_to_assets", "op": "above_median"}],
        "select": {"metric": "net_margin", "direction": "max"},
        "answer": {"metric": "net_margin", "aggregate": "mean", "unit": "%"},
    },
)
check("median filter then aggregate mean", answer is not None and abs(answer[0] - 20.0) < 1e-12)


scenario_data = {
    "GEX": {
        "2024": {
            "current_assets": 90.0,
            "inventory": 20.0,
            "short_term_debt": 100.0,
            "profit_before_tax": 30.0,
            "interest_expense": -10.0,
        }
    },
    "VGC": {
        "2024": {
            "current_assets": 200.0,
            "inventory": 50.0,
            "short_term_debt": 100.0,
            "profit_before_tax": 50.0,
            "interest_expense": -10.0,
        }
    },
    "PC1": {
        "2024": {
            "current_assets": 130.0,
            "inventory": 30.0,
            "short_term_debt": 100.0,
            "profit_before_tax": 80.0,
            "interest_expense": -10.0,
        }
    },
}
answer = execute_fact_plan(
    scenario_data,
    {
        "median_filter_mentioned": True,
        "universe": {"tickers": ["GEX", "VGC", "PC1"], "years": [2024]},
        "filters": [{"metric": "quick_ratio", "op": "below_median"}],
        "scenario": {"kind": "ebit_proxy_multiplier", "multiplier": 0.85},
        "select": {"metric": "scenario_icr", "direction": "min"},
        "answer": {"metric": "scenario_icr", "unit": "lần"},
    },
)
check("scenario ICR uses changed EBIT proxy", answer is not None and abs(answer[0] - 3.4) < 1e-12)


inventory_release_data = {
    "LOW": {"2024": {"inventory": 400_000_000_000.0, "cogs": -3_650_000_000_000.0}},
    "MID": {"2024": {"inventory": 800_000_000_000.0, "cogs": -3_650_000_000_000.0}},
    "HIGH": {"2024": {"inventory": 1_000_000_000_000.0, "cogs": -3_650_000_000_000.0}},
}
answer = execute_fact_plan(
    inventory_release_data,
    {
        "median_filter_mentioned": True,
        "universe": {"tickers": ["LOW", "MID", "HIGH"], "years": [2024]},
        "filters": [{"metric": "inventory_days", "op": "above_median"}],
        "select": {"metric": "inventory_days", "direction": "max"},
        "answer": {"metric": "inventory_release_to_median", "unit": "VND"},
    },
    unit_hint="tỷ đồng",
)
check("inventory-days release converts to billion VND", answer is not None and abs(answer[0] - 200.0) < 1e-9)


fixed_asset_data = {
    "DBC": {
        "2023": {"fixed_assets": 80.0},
        "2024": {"fixed_assets": 120.0, "net_revenue": 200.0},
    },
    "MSN": {
        "2023": {"fixed_assets": 180.0},
        "2024": {"fixed_assets": 220.0, "net_revenue": 300.0},
    },
    "OGC": {
        "2023": {"fixed_assets": 90.0},
        "2024": {"fixed_assets": 110.0, "net_revenue": 500.0},
    },
}
answer = execute_fact_plan(
    fixed_asset_data,
    {
        "median_filter_mentioned": True,
        "universe": {"tickers": ["DBC", "MSN", "OGC"], "years": [2024]},
        "filters": [{"metric": "fixed_asset_turnover", "op": "below_median"}],
        "select": {"metric": "avg_fixed_assets", "direction": "max"},
        "answer": {"metric": "fixed_asset_turnover", "unit": "lần"},
    },
)
check("fixed asset turnover filter can select by average fixed assets", answer is not None and answer[0] == 1.5)


growth_data = {
    "HPG": {
        "2023": {"net_revenue": 100.0, "operating_profit": 10.0},
        "2024": {"net_revenue": 110.0, "operating_profit": 22.0},
    },
    "HSG": {
        "2023": {"net_revenue": 100.0, "operating_profit": 10.0},
        "2024": {"net_revenue": 102.0, "operating_profit": 20.0},
    },
    "NKG": {
        "2023": {"net_revenue": 100.0, "operating_profit": -10.0},
        "2024": {"net_revenue": 120.0, "operating_profit": 30.0},
    },
}
answer = execute_fact_plan(
    growth_data,
    {
        "universe": {"tickers": ["HPG", "HSG", "NKG"], "years": [2024]},
        "filters": [
            {"metric": "revenue_growth", "op": ">", "value": 0.03},
            {"metric": "operating_profit", "op": ">", "value": 0},
            {"metric": "prev_operating_profit", "op": ">", "value": 0},
        ],
        "select": {"metric": "operating_leverage", "direction": "max"},
        "answer": {"metric": "operating_margin", "unit": "phần trăm"},
    },
)
check("growth and prior-period filters support operating leverage", answer is not None and answer[0] == 20.0)


offset_data = {
    "VRE": {
        "2021": {"current_assets": 300.0, "inventory": 80.0, "short_term_debt": 100.0},
        "2022": {
            "current_assets": 260.0,
            "inventory": 100.0,
            "short_term_debt": 100.0,
            "net_cash_operating": 12.0,
        },
    }
}
answer = execute_fact_plan(
    offset_data,
    {
        "universe": {"tickers": ["VRE"], "years": [2021]},
        "select": {"metric": "quick_ratio", "direction": "min", "offset_years": 1},
        "answer": {"metric": "cfo_to_short_term_debt", "unit": "lần"},
    },
)
check("selected-row answer can shift to the next year", answer is not None and answer[0] == 0.12)


plan = FactPlan.model_validate(
    {
        "filters": [{"metric": "gross_margin", "op": "below_median"}],
        "answer": {"metric": "roe"},
    }
)
check("median-relative fact filter normalizes the median flag", plan.median_filter_mentioned)

print("tất cả PASS")
