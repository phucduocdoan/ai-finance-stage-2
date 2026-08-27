"""Regression tests for solve-result emission bookkeeping."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.common.solution import PandasSolution  # noqa: E402
from finance_qa.modules.solve.pipeline.emit import emit_result, emit_solver_result  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def result(query: str) -> dict:
    return {
        "answer": 42.0,
        "pandas_query": query,
        "errors": [],
        "diag": {"failed": False},
        "solution": PandasSolution(
            table_variable="df10",
            target_row="row",
            target_column="col",
            pandas_query=query,
        ),
    }


state = {
    "table_ids": ["AAA_financial_statements_2024_consolidated|1"],
    "names": {
        "df1": "AAA_financial_statements_2024_consolidated|1",
        "df10": "BBB_financial_statements_2024_consolidated|10",
    },
    "evidence": [{"variable": "df1", "csv_path": "data/fallback.csv"}],
    "errors": [],
    "diag": {},
    "evidence_tables": ["AAA_financial_statements_2024_consolidated|1"],
}

emitted = emit_result(state, result("float(df10.iloc[0, 0])"))

check("default emitted solver is codegen", emitted["solver"] == "codegen")
check("df10 does not also mark df1 as read", [ev["variable"] for ev in emitted["evidence"]] == ["df10"])
check(
    "a read table missing from retrieval ids is appended",
    emitted["table_ids"]
    == [
        "AAA_financial_statements_2024_consolidated|1",
        "BBB_financial_statements_2024_consolidated|10",
    ],
)

fallback = emit_result(state, result("42.0"))

check("queries with no dataframe reads keep fallback evidence", fallback["evidence"] == state["evidence"])

raw = emit_result(state, result("float(df10.iloc[0, 0])"), solver="raw_table_linker")

check("explicit emitted solver is preserved", raw["solver"] == "raw_table_linker")

frames = {"df1": object(), "df10": object()}
narrow = emit_solver_result(
    state,
    "raw_selection_linker",
    result("float(df10.iloc[0, 0])"),
    {"source": "raw"},
    frames=frames,
    names=state["names"],
    evidence_tables=["AAA_financial_statements_2024_consolidated|1"],
    solution={"pandas_query": "float(df10.iloc[0, 0])"},
    table_ids=["AAA_financial_statements_2024_consolidated|1", "PREP|2"],
    codegen_prompt="",
)

check("narrow emit stores solver name", narrow["solver"] == "raw_selection_linker")
check("narrow emit marks solver diag done", narrow["diag"]["raw_selection_linker"]["status"] == "done")
check("narrow emit keeps frames and names", narrow["frames"] is frames and narrow["names"] is state["names"])
check("narrow emit keeps empty prompt", narrow["codegen_prompt"] == "")
check(
    "narrow emit uses table override then appends read table",
    narrow["table_ids"]
    == [
        "AAA_financial_statements_2024_consolidated|1",
        "PREP|2",
        "BBB_financial_statements_2024_consolidated|10",
    ],
)

print("tất cả PASS")
