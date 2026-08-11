"""Tests for deterministic fact-table materialization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.codegen.facts import materialize_fact_table


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


data = {
    "AAA": {
        "2023": {
            "net_revenue": 100.0,
            "operating_profit": 10.0,
            "fixed_assets": 40.0,
            "inventory": 8.0,
            "cogs": -80.0,
        },
        "2024": {
            "net_revenue": 120.0,
            "operating_profit": 18.0,
            "fixed_assets": 60.0,
            "inventory": 10.0,
            "cogs": -90.0,
        },
    }
}

table = materialize_fact_table(
    data,
    tickers=["AAA"],
    years=[2024],
    metrics=[
        "net_revenue",
        "operating_margin",
        "revenue_growth",
        "operating_profit_growth",
        "operating_leverage",
        "inventory_days",
        "fixed_asset_turnover",
    ],
)

row = table.rows[0]
check("one ticker/year row is materialized", row.ticker == "AAA" and row.year == 2024)
check("raw metric is preserved", row.get("net_revenue") == 120.0)
check("operating margin is derived", abs(row.get("operating_margin") - 0.15) < 1e-12)
check("revenue growth uses prior year", abs(row.get("revenue_growth") - 0.2) < 1e-12)
check("operating leverage can depend on derived growth metrics", abs(row.get("operating_leverage") - 4.0) < 1e-12)
check("inventory days is available", abs(row.get("inventory_days") - (10 / 90 * 365)) < 1e-12)
check("fixed asset turnover uses average fixed assets", abs(row.get("fixed_asset_turnover") - 2.4) < 1e-12)
check("availability counts finite metrics", table.available_metrics()["operating_leverage"] == 1)

try:
    materialize_fact_table(data, metrics=["does_not_exist"])
    raised = False
except ValueError as exc:
    raised = "does_not_exist" in str(exc)
check("unknown metric is rejected", raised)

print("tất cả PASS")
