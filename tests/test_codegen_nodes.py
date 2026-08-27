"""No-LLM regression tests for codegen pipeline nodes."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.agents.finance.config import FinanceAgentConfig  # noqa: E402
from finance_qa.modules.solve.common.solution import PandasSolution  # noqa: E402
from finance_qa.modules.solve.pipeline.nodes import codegen as codegen_nodes  # noqa: E402


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


orig_load_evidence = codegen_nodes.load_evidence
try:
    codegen_nodes.load_evidence = lambda table_ids, max_tables: ({}, {}, ["load failed"])
    generated = asyncio.run(
        codegen_nodes.make_generate_pandas(FinanceAgentConfig())(
            {
                "question": "Doanh thu là bao nhiêu?",
                "table_ids": ["AAA_financial_statements_2024_consolidated|1"],
                "errors": ["previous"],
            }
        )
    )
finally:
    codegen_nodes.load_evidence = orig_load_evidence

check("generate_pandas reports no frames without calling LLM", generated["codegen_prompt"] == "")
check("generate_pandas keeps previous and load errors", generated["errors"][:2] == ["previous", "load failed"])
check("generate_pandas adds the no-table error", generated["errors"][-1] == "codegen: không có bảng nào để đọc")


seen: dict = {}


async def fake_aexecute(solution, prompt, frames, **kwargs):
    seen["solution"] = solution
    seen["prompt"] = prompt
    seen["frames"] = frames
    seen["kwargs"] = kwargs
    return {"answer": 1.0, "pandas_query": "df1.iloc[0, 0]", "solution": solution}


def fake_emit(state, result):
    seen["emit_state"] = state
    seen["emit_result"] = result
    return {"answer": result["answer"], "solver": "codegen"}


orig_aexecute = codegen_nodes.aexecute
orig_emit = codegen_nodes.emit_result
try:
    codegen_nodes.aexecute = fake_aexecute
    codegen_nodes.emit_result = fake_emit
    solution = PandasSolution(table_variable="df1", pandas_query="df1.iloc[0, 0]")
    executed = asyncio.run(
        codegen_nodes.make_execute_and_repair(FinanceAgentConfig(max_repairs=1))(
            {
                "question": "Lợi nhuận là bao nhiêu?",
                "solution": solution.model_dump(),
                "codegen_prompt": "PROMPT",
                "frames": {"df1": object()},
                "names": {"df1": "AAA_financial_statements_2024_consolidated|1"},
                "tickers": ["AAA"],
                "unit_hint": "triệu đồng",
            }
        )
    )
finally:
    codegen_nodes.aexecute = orig_aexecute
    codegen_nodes.emit_result = orig_emit

check("execute node delegates to emitter", executed == {"answer": 1.0, "solver": "codegen"})
check("execute node validates the stored solution", isinstance(seen["solution"], PandasSolution))
check("execute node passes prompt through", seen["prompt"] == "PROMPT")
check("execute node passes max_repairs from config", seen["kwargs"]["max_repairs"] == 1)
check("execute node passes names through", seen["kwargs"]["names"] == {"df1": "AAA_financial_statements_2024_consolidated|1"})

print("tất cả PASS")
