"""Offline tests for TableProfile-based post-solve diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.facts import profile_validate, table_profile  # noqa: E402
from finance_qa.agents.finance.config import FinanceAgentConfig  # noqa: E402
from finance_qa.agents.finance.graph import make_profile_validate  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


TABLE_ID = "AAA_financial_statements_2024_consolidated|7"
FRAME = pd.DataFrame(
    {
        "Mã số": ["10", "60"],
        "Chỉ tiêu": ["Doanh thu thuần", "Lợi nhuận sau thuế"],
        "Năm nay": [1_200_000.0, 100_000.0],
        "Năm trước": [900_000.0, 80_000.0],
    }
)
FRAMES = {"df1": FRAME}
NAMES = {"df1": TABLE_ID}


def base_state(query: str, *, metric: str = "net_revenue", years=None, multi_year: bool = False) -> dict:
    return {
        "id": 1,
        "question": "Năm 2024, doanh thu thuần của AAA là bao nhiêu triệu đồng?",
        "years": [2024] if years is None else years,
        "tickers": ["AAA"],
        "multi_year": multi_year,
        "multi_company": False,
        "metric": metric,
        "unit_hint": "triệu đồng",
        "answer": 1_200_000.0,
        "pandas_query": query,
        "solution": {
            "table_variable": "df1",
            "target_row": "Doanh thu thuần",
            "target_column": "Năm nay",
            "source_unit": "million_vnd",
            "target_unit": "million_vnd",
            "pandas_query": query,
        },
        "diag": {"units": {"source_unit": "million_vnd"}},
    }


def codes(diag: dict) -> set[str]:
    return {finding["code"] for finding in diag["findings"]}


old_meta_for = table_profile.meta_for
old_page_text = table_profile.page_text

try:
    table_profile.meta_for = lambda table_id: {  # type: ignore[assignment]
        "ticker": "AAA",
        "year": 2024,
        "doc_type": "consolidated",
        "statement_type": "income_statement",
        "note_title": "",
    }
    table_profile.page_text = lambda table_id: ""  # type: ignore[assignment]

    refs = profile_validate.query_cell_refs('df1.iloc[0]["Năm nay"] / df1.iloc[1, 2]')
    check("query parser extracts iloc bracket cells", len(refs) == 2)
    check("query parser keeps column labels", refs[0].column == "Năm nay")
    check("query parser keeps column positions", refs[1].column_index == 2)

    ok_diag = profile_validate.validate_profile_selection(
        base_state('df1.iloc[0]["Năm nay"]'),
        FRAMES,
        NAMES,
    )
    check("correct cell has no strong finding", ok_diag["summary"]["strong"] == 0)
    check("correct cell resolves row metric", ok_diag["query_cells"][0]["row_metrics"] == ["net_revenue"])

    wrong_year = profile_validate.validate_profile_selection(
        base_state('df1.iloc[0]["Năm trước"]'),
        FRAMES,
        NAMES,
    )
    check("validator flags wrong year column", "column_year_mismatch" in codes(wrong_year))

    wrong_row = profile_validate.validate_profile_selection(
        base_state('df1.iloc[1]["Năm nay"]'),
        FRAMES,
        NAMES,
    )
    check("validator flags row metric mismatch", "row_metric_mismatch" in codes(wrong_row))

    multi = base_state('df1.iloc[0]["Năm nay"]', years=[2023, 2024], multi_year=True)
    multi["question"] = "Chênh lệch doanh thu thuần của AAA năm 2024 so với 2023 là bao nhiêu triệu đồng?"
    multi_diag = profile_validate.validate_profile_selection(multi, FRAMES, NAMES)
    check("validator flags multi-axis single-cell query", "multi_axis_single_cell" in codes(multi_diag))

    graph_state = {**base_state('df1.iloc[0]["Năm nay"]'), "frames": FRAMES, "names": NAMES}
    enabled_node = make_profile_validate(FinanceAgentConfig(profile_validate=True))
    disabled_node = make_profile_validate(FinanceAgentConfig(profile_validate=False))
    enabled_out = enabled_node(graph_state)
    check("graph node attaches profile diag when enabled", "profile_validate" in enabled_out["diag"])
    check("graph node is no-op when disabled", disabled_node(graph_state) == {})
finally:
    table_profile.meta_for = old_meta_for  # type: ignore[assignment]
    table_profile.page_text = old_page_text  # type: ignore[assignment]

print("tất cả PASS")
