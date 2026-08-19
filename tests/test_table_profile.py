"""Offline tests for deterministic table profiles."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve import table_profile  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


FRAME = pd.DataFrame({
    "Mã số": ["10", "20", "60"],
    "Chỉ tiêu": [
        "Doanh thu thuần",
        "Lợi nhuận gộp",
        "Lợi nhuận sau thuế",
    ],
    "Số cuối năm Triệu đồng": [1_000_000_000.0, 250_000_000.0, 80_000_000.0],
    "Số đầu năm Triệu đồng": [900_000_000.0, 200_000_000.0, 50_000_000.0],
})


table_profile.meta_for = lambda table_id: {  # type: ignore[assignment]
    "ticker": "AAA",
    "year": 2024,
    "doc_type": "consolidated",
    "statement_type": "income_statement",
}
table_profile.page_text = lambda table_id: ""  # type: ignore[assignment]

profile = table_profile.build_table_profile("AAA_financial_statements_2024_consolidated|7", FRAME)

check("profile keeps table identity", profile.table_id == "AAA_financial_statements_2024_consolidated|7")
check("profile carries metadata", profile.ticker == "AAA" and profile.year == 2024)
check("profile identifies label column", profile.label_columns == ["Chỉ tiêu"])
check("profile identifies ma_so code column", profile.columns[0].role == "code")
check("profile identifies money columns", profile.columns[2].role == "numeric")
check("current-period column maps to report year", profile.columns[2].year == 2024)
check("prior-period column maps to previous year", profile.columns[3].year == 2023)
check("column unit is detected", profile.columns[2].unit == "million_vnd")
check("row positions are iloc positions", [row.position for row in profile.rows] == [0, 1, 2])
check("metric candidates are attached", profile.rows[0].metric_candidates == ["net_revenue"])

rendered = table_profile.render_table_profile(profile)
check("render includes row positions", "r2: Lợi nhuận sau thuế" in rendered)
check("render includes column map", "[2] Số cuối năm Triệu đồng: numeric, năm 2024" in rendered)

print("tất cả PASS")
