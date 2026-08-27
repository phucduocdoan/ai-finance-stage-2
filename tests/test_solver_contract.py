"""Audit the normalized solver diagnostic contract.

This stays no-LLM and no-data: node dependencies are monkeypatched so the test
only checks the state contract that downstream routing/debugging relies on.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.agents.finance.config import FinanceAgentConfig  # noqa: E402
from finance_qa.modules.solve.common.solution import PandasSolution  # noqa: E402
from finance_qa.modules.solve.pipeline.nodes import solvers  # noqa: E402
from finance_qa.modules.solve.pipeline.outcome import (  # noqa: E402
    SolverStatus,
    declined,
    done_payload,
    errored,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


def assert_contract(label: str, update: dict, solver: str, status: SolverStatus) -> None:
    diag = (update.get("diag") or {}).get(solver)
    check(f"{label} has solver diag", isinstance(diag, dict))
    check(f"{label} has status", diag.get("status") == status)
    check(f"{label} has done flag", diag.get("done") is (status == "done"))
    check(f"{label} has string reason", isinstance(diag.get("reason"), str))


BASE_STATE = {
    "question": "Doanh thu của AAA năm 2024 là bao nhiêu?",
    "years": [2024],
    "tickers": ["AAA"],
    "table_ids": ["AAA|2024|0"],
    "shortlist": [],
    "diag": {"existing": True},
    "errors": [],
}


assert_contract(
    "helper decline",
    declined(BASE_STATE, "raw_table_linker", "missing candidates"),
    "raw_table_linker",
    "declined",
)
assert_contract(
    "helper error",
    errored(BASE_STATE, "cell_locator", "ValueError: bad table"),
    "cell_locator",
    "error",
)
assert_contract(
    "done payload normalizes reason",
    {"diag": {"formula_facts": done_payload({"reason": None})}},
    "formula_facts",
    "done",
)


original_formula = solvers.asolve_formula_facts


async def fake_formula(_state, *, planner_thinking=False):
    return {
        "answer": 12.0,
        "pandas_query": "float(12)",
        "evidence": [{"variable": "df1", "csv_path": "data/AAA_2024.csv"}],
        "table_ids": ["AAA|2024|1"],
        "diag": {"source": "formula"},
    }


try:
    solvers.asolve_formula_facts = fake_formula
    formula_done = asyncio.run(
        solvers.make_solve_formula_facts(FinanceAgentConfig())(BASE_STATE)
    )
finally:
    solvers.asolve_formula_facts = original_formula

assert_contract("formula node success", formula_done, "formula_facts", "done")


original_locate = solvers.locate_single_cell


def fake_no_cell(_state, *, table_ids, shortlist):
    return None, {"reason": "no located cell"}


try:
    solvers.locate_single_cell = fake_no_cell
    cell_decline = asyncio.run(
        solvers.make_solve_single_cell(FinanceAgentConfig())(BASE_STATE)
    )
finally:
    solvers.locate_single_cell = original_locate

assert_contract("cell locator node decline", cell_decline, "cell_locator", "declined")


original_raw_table = solvers.aprepare_raw_table_linker


async def fake_raw_table_error(_state, **_kwargs):
    raise ValueError("boom")


try:
    solvers.aprepare_raw_table_linker = fake_raw_table_error
    raw_error = asyncio.run(
        solvers.make_solve_raw_table_linker(FinanceAgentConfig())(BASE_STATE)
    )
finally:
    solvers.aprepare_raw_table_linker = original_raw_table

assert_contract("raw table node error", raw_error, "raw_table_linker", "error")


class FakePlan:
    rank_metric = "rank metric"
    filter_metric = ""
    answer_metric = "answer metric"

    def model_dump(self) -> dict:
        return {
            "rank_metric": self.rank_metric,
            "filter_metric": self.filter_metric,
            "answer_metric": self.answer_metric,
        }


def fake_axis_of(_question, _years, _tickers):
    return "year", [2023, 2024]


async def fake_aplan(_question, _axis, _elements):
    return FakePlan()


def fake_sub_question(template, axis, element, fixed):
    return f"{template} {axis} {element} {fixed}".strip() if template else ""


def fake_tables_for(_table_ids, _axis, element):
    return [f"AAA|{element}|1"]


def fake_pick(_plan, _axis, _rank, _filter):
    return 2024, {"reason": "picked latest"}


async def fake_sub_value(_question, table_ids, _config):
    table_id = table_ids[0]
    solution = PandasSolution(
        table_variable="df1",
        target_row="row",
        target_column="col",
        pandas_query="float(df1.iloc[0, 0])",
    )
    return {
        "value": 10.0 if "2024" in table_id else 1.0,
        "frames": {"df1": object()},
        "names": {"df1": table_id},
        "prompt": "prompt",
        "result": {
            "answer": 10.0,
            "pandas_query": "float(df1.iloc[0, 0])",
            "errors": [],
            "diag": {"failed": False},
            "solution": solution,
        },
    }


original_axis_of = solvers.axis_of
original_aplan = solvers.aplan
original_sub_question = solvers.sub_question
original_tables_for = solvers.tables_for
original_pick = solvers.pick
original_sub_value = solvers.asub_value

try:
    solvers.axis_of = fake_axis_of
    solvers.aplan = fake_aplan
    solvers.sub_question = fake_sub_question
    solvers.tables_for = fake_tables_for
    solvers.pick = fake_pick
    solvers.asub_value = fake_sub_value
    selection_done = asyncio.run(
        solvers.make_solve_selection(FinanceAgentConfig())(
            {**BASE_STATE, "years": [2023, 2024]}
        )
    )
finally:
    solvers.axis_of = original_axis_of
    solvers.aplan = original_aplan
    solvers.sub_question = original_sub_question
    solvers.tables_for = original_tables_for
    solvers.pick = original_pick
    solvers.asub_value = original_sub_value

assert_contract("selection node success", selection_done, "selection", "done")

print("tất cả PASS")
