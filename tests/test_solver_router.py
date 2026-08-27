"""Pure routing checks for the solve graph's solver chain."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.agents.finance.config import FinanceAgentConfig  # noqa: E402
from finance_qa.modules.solve.pipeline.router import (  # noqa: E402
    make_solver_router,
    route_after_selection,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


BASE_STATE = {
    "question": "Năm nào doanh thu thuần cao nhất trong giai đoạn 2020-2021?",
    "years": [2020, 2021],
    "tickers": ["ABC"],
}


cfg = FinanceAgentConfig()
route, destinations = make_solver_router(cfg, None)
check("default first solver is cell locator", route(BASE_STATE) == "solve_single_cell")
check("initial destinations include the whole chain", "solve_raw_table_linker" in destinations)

after_cell, destinations = make_solver_router(cfg, "solve_single_cell")
done_state = {**BASE_STATE, "diag": {"cell_locator": {"done": True}}}
check("a done solver routes to verify", after_cell(done_state) == "verify_answer")
status_done_state = {**BASE_STATE, "diag": {"cell_locator": {"status": "done"}}}
check("status=done also routes to verify", after_cell(status_done_state) == "verify_answer")
check("post-solver destinations include verify", "verify_answer" in destinations)

cfg_no_cell = replace(cfg, cell_locator=False)
route_no_cell, _ = make_solver_router(cfg_no_cell, None)
check("disabled cell locator falls through to formula facts", route_no_cell(BASE_STATE) == "solve_formula_facts")

cfg_codegen = replace(
    cfg,
    cell_locator=False,
    formula_facts=False,
    raw_table_linker=False,
    selection_facts=False,
    raw_selection_linker=False,
    structured_facts=False,
    selection_decompose=False,
)
route_codegen, _ = make_solver_router(cfg_codegen, None)
check("all solvers off falls back to codegen", route_codegen(BASE_STATE) == "generate_pandas")

cfg_selection = replace(cfg_codegen, selection_decompose=True)
route_selection, _ = make_solver_router(cfg_selection, None)
check("selection fan-out is the last non-codegen fallback", route_selection(BASE_STATE) == "solve_selection")

check(
    "selection completion routes to verify",
    route_after_selection({"diag": {"selection": {"done": True}}}) == "verify_answer",
)
check(
    "selection status=done routes to verify",
    route_after_selection({"diag": {"selection": {"status": "done"}}}) == "verify_answer",
)
check(
    "selection miss routes to codegen",
    route_after_selection({"diag": {"selection": {"done": False}}}) == "generate_pandas",
)
