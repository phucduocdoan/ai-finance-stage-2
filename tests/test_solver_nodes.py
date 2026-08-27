"""No-LLM regression tests for solver node factories."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.agents.finance.config import FinanceAgentConfig  # noqa: E402
from finance_qa.modules.solve.common.solution import PandasSolution  # noqa: E402
from finance_qa.modules.solve.pipeline.nodes import solvers  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


state = {
    "question": "Doanh thu của AAA năm 2024 là bao nhiêu?",
    "years": [2024],
    "tickers": ["AAA"],
    "table_ids": [],
    "shortlist": [],
    "diag": {"existing": True},
}

trace_node = solvers.make_trace_capabilities(FinanceAgentConfig())
trace = trace_node(state)

check("trace node preserves existing diag", trace["diag"]["existing"] is True)
check("trace node records capability router", "capability_router" in trace["diag"])

single_cell_off = solvers.make_solve_single_cell(FinanceAgentConfig(cell_locator=False))
miss = asyncio.run(single_cell_off(state))

check("disabled single-cell solver is a no-op", miss == {})


def fake_result(solver_name: str) -> dict:
    return {
        "answer": 12.0,
        "pandas_query": "float(12)",
        "evidence": [{"variable": "df1", "csv_path": "data/AAA_2024.csv"}],
        "table_ids": ["AAA|2024|1"],
        "diag": {"source": solver_name},
    }


fact_state = {**state, "table_ids": ["AAA|2024|0"], "errors": ["old"]}

original_structured = solvers.asolve_structured_facts
original_selection = solvers.asolve_selection_facts
original_formula = solvers.asolve_formula_facts


async def fake_structured(_state, *, planner_thinking=False):
    return fake_result("structured_facts")


async def fake_selection(_state):
    return fake_result("selection_facts")


async def fake_formula(_state, *, planner_thinking=False):
    return fake_result("formula_facts")


try:
    solvers.asolve_structured_facts = fake_structured
    solvers.asolve_selection_facts = fake_selection
    solvers.asolve_formula_facts = fake_formula

    structured = asyncio.run(
        solvers.make_solve_structured_facts(FinanceAgentConfig())(fact_state)
    )
    selection = asyncio.run(
        solvers.make_solve_selection_facts(FinanceAgentConfig())(fact_state)
    )
    formula = asyncio.run(
        solvers.make_solve_formula_facts(FinanceAgentConfig())(fact_state)
    )
finally:
    solvers.asolve_structured_facts = original_structured
    solvers.asolve_selection_facts = original_selection
    solvers.asolve_formula_facts = original_formula


for solver_name, out in [
    ("structured_facts", structured),
    ("selection_facts", selection),
    ("formula_facts", formula),
]:
    check(f"{solver_name} writes solver name", out["solver"] == solver_name)
    check(f"{solver_name} marks diag done", out["diag"][solver_name]["status"] == "done")
    check(f"{solver_name} preserves prior diag", out["diag"]["existing"] is True)
    check(
        f"{solver_name} appends fact table ids",
        out["table_ids"] == ["AAA|2024|0", "AAA|2024|1"],
    )
    check(f"{solver_name} preserves errors", out["errors"] == ["old"])
    check(f"{solver_name} leaves codegen prompt empty", out["codegen_prompt"] == "")
    check(f"{solver_name} leaves frames empty", out["frames"] == {} and out["names"] == {})


solution = PandasSolution(
    table_variable="df1",
    target_row="row",
    target_column="col",
    pandas_query="float(df1.iloc[0, 0])",
)
prepared = {
    "solution": solution,
    "frames": {"df1": object()},
    "names": {"df1": "AAA|2024|1"},
    "table_ids": ["AAA|2024|1", "AAA|2024|2"],
    "diag": {"source": "prepared"},
}
exec_result = {
    "answer": 7.0,
    "pandas_query": "float(df1.iloc[0, 0])",
    "errors": [],
    "diag": {"failed": False},
    "solution": solution,
}

original_raw_table = solvers.aprepare_raw_table_linker
original_raw_selection = solvers.aprepare_raw_selection_linker
original_execute = solvers.aexecute
original_locate = solvers.locate_single_cell
original_load_frame = solvers.load_frame


async def fake_raw_table(_state, **_kwargs):
    return prepared


async def fake_raw_selection(_state, **_kwargs):
    return prepared


async def fake_execute(*_args, **_kwargs):
    return exec_result


class FakeHit:
    table_id = "AAA|2024|1"

    def solution(self, variable):
        return PandasSolution(
            table_variable=variable,
            target_row="row",
            target_column="col",
            pandas_query=f"float({variable}.iloc[0, 0])",
        )


def fake_locate(_state, *, table_ids, shortlist):
    return FakeHit(), {"source": "cell"}


def fake_load_frame(_table_id):
    return object()


try:
    solvers.aprepare_raw_table_linker = fake_raw_table
    solvers.aprepare_raw_selection_linker = fake_raw_selection
    solvers.aexecute = fake_execute
    solvers.locate_single_cell = fake_locate
    solvers.load_frame = fake_load_frame

    raw_state = {**state, "table_ids": ["AAA|2024|0"], "errors": ["old"]}
    raw_table = asyncio.run(
        solvers.make_solve_raw_table_linker(FinanceAgentConfig())(raw_state)
    )
    raw_selection = asyncio.run(
        solvers.make_solve_raw_selection_linker(FinanceAgentConfig())(raw_state)
    )
    cell = asyncio.run(
        solvers.make_solve_single_cell(FinanceAgentConfig())(raw_state)
    )
finally:
    solvers.aprepare_raw_table_linker = original_raw_table
    solvers.aprepare_raw_selection_linker = original_raw_selection
    solvers.aexecute = original_execute
    solvers.locate_single_cell = original_locate
    solvers.load_frame = original_load_frame


for solver_name, out in [
    ("raw_table_linker", raw_table),
    ("raw_selection_linker", raw_selection),
    ("cell_locator", cell),
]:
    check(f"{solver_name} execute-backed solver name", out["solver"] == solver_name)
    check(f"{solver_name} execute-backed diag done", out["diag"][solver_name]["status"] == "done")
    check(f"{solver_name} execute-backed answer", out["answer"] == 7.0)
    check(f"{solver_name} execute-backed prompt empty", out["codegen_prompt"] == "")
    check(f"{solver_name} execute-backed frames carried", out["frames"])
    check(f"{solver_name} execute-backed names carried", out["names"])

check(
    "raw table linker appends only read prepared table",
    raw_table["table_ids"] == ["AAA|2024|0", "AAA|2024|1"],
)
check(
    "raw selection linker keeps all prepared table ids",
    raw_selection["table_ids"] == ["AAA|2024|0", "AAA|2024|1", "AAA|2024|2"],
)
check(
    "cell locator appends located table",
    cell["table_ids"] == ["AAA|2024|0", "AAA|2024|1"],
)

print("tất cả PASS")
