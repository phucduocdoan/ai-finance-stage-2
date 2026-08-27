"""Codegen-oriented LangGraph nodes for the solve pipeline."""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.modules.data.table_store import submission_csv_name
from finance_qa.modules.solve.codegen.legacy import agenerate, build_prompt
from finance_qa.modules.solve.codegen.execute import aexecute
from finance_qa.modules.solve.codegen.screening import agenerate_screening
from finance_qa.modules.solve.common.screening import is_screening
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.solve.common.units import unit_from_hint
from finance_qa.modules.solve.pipeline.emit import emit_result
from finance_qa.modules.solve.pipeline.evidence import codegen_budget, load_evidence
from finance_qa.modules.solve.solvers.decompose import degenerate_query


State = Mapping[str, Any]


def make_generate_pandas(config: FinanceAgentConfig):
    async def generate_pandas(state: State) -> dict:
        table_ids, max_tables = codegen_budget(state, config)
        names, frames, errors = load_evidence(table_ids, max_tables)
        errors = list(state.get("errors") or []) + errors
        loaded = {
            "evidence_tables": list(names.values()),
            "frames": frames,
            "names": names,
            "evidence": [
                {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
                for var, tid in names.items()
            ],
        }
        if not frames:
            return {
                **loaded,
                "solution": PandasSolution().model_dump(),
                "codegen_prompt": "",
                "errors": errors + ["codegen: không có bảng nào để đọc"],
            }
        # A screening question routes to the predicate-shaped schema instead of
        # the plain one-expression codegen: see `screening_solver`'s comment in
        # config.py for the class this targets and the baseline it must beat.
        screening = config.screening_solver and is_screening(state["question"])
        try:
            if screening:
                solution, prompt, tool_calls = await agenerate_screening(
                    state["question"], frames, names,
                    thinking=config.codegen_thinking,
                    shortlist=list(state.get("shortlist") or []),
                    tool_turns=config.codegen_tool_turns,
                    show_grids=config.codegen_show_grids,
                )
            else:
                solution, prompt, tool_calls = await agenerate(
                    state["question"], frames, names,
                    thinking=config.codegen_thinking,
                    shortlist=list(state.get("shortlist") or []),
                    tool_turns=config.codegen_tool_turns,
                    show_grids=config.codegen_show_grids,
                    metric=state.get("metric") or "",
                    use_metric_hints=config.codegen_metric_hints,
                    metric_lookup=config.codegen_metric_lookup,
                    use_table_profiles=config.codegen_table_profiles,
                )
            # `agenerate`/`agenerate_screening` bind any table their lookups
            # surfaced into `names`/`frames`.
            loaded = {**loaded, "names": names, "frames": frames,
                      "evidence_tables": list(names.values()),
                      "evidence": [
                          {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
                          for var, tid in names.items()
                      ]}
        except Exception as exc:  # noqa: BLE001 - reported, execute node handles the empty query
            # The prompt is handed on even though generation failed: the repair
            # call is the only remaining attempt, and a repair without the grids
            # answers `df1.iloc[0, 0]` — which is what the first measured run did
            # on all 26 questions whose codegen call was truncated. A screening
            # plan that fails `compose` (`ValueError`) lands here too, by the
            # same "reported, not crashed" contract as any other codegen failure.
            return {
                **loaded,
                "solution": PandasSolution().model_dump(),
                "codegen_prompt": build_prompt(
                    state["question"], frames, names,
                    metric=state.get("metric") or "",
                    use_metric_hints=config.codegen_metric_hints,
                    use_table_profiles=config.codegen_table_profiles,
                ),
                "errors": errors + [f"codegen: {exc}"],
                "diag": {**(state.get("diag") or {}), "screening_solver": screening},
            }
        return {
            **loaded,
            "solution": solution.model_dump(),
            "codegen_prompt": prompt,
            "errors": errors,
            "diag": {
                **(state.get("diag") or {}),
                "tool_calls": tool_calls,
                "screening_solver": screening,
            },
        }

    return generate_pandas


def make_execute_and_repair(config: FinanceAgentConfig):
    async def execute_and_repair(state: State) -> dict:
        solution = PandasSolution.model_validate(state.get("solution") or {})
        result = await aexecute(
            solution,
            state.get("codegen_prompt") or "",
            state.get("frames") or {},
            question=state["question"],
            unit_hint=state.get("unit_hint") or "",
            names=state.get("names") or {},
            tickers=state.get("tickers") or [],
            max_repairs=config.max_repairs,
            repair_history=config.repair_history,
        )
        return emit_result(state, result)

    return execute_and_repair


# Unit target for a sub-question that names no unit of its own, so the N money
# values being compared land on one scale. Without it the target comes from the
# model's `target_unit`, which it re-decides per call: one year normalised to
# "tỷ đồng" next to another left in đồng makes `max()` pick the wrong element
# while every query runs cleanly and reports nothing.
#
# Applied only to those. Pinning it unconditionally is worse than not pinning at
# all: a sub-question asking for a ratio ("bao nhiêu lần") would be given a money
# target, and a table declaring "Triệu đồng" then multiplies the ratio by 1e6 —
# measured on q363, whose D/E series came back 0.88, 0.87, 1.5e13, 1.4e13, 66.9.
_SUB_UNIT_HINT = "đồng"


async def asub_value(
    question: str, table_ids: list[str], config: FinanceAgentConfig
) -> dict | None:
    """Answer one sub-question against one element's own tables.

    The slice is `selection_sub_tables`, which is wider than the one
    `generate_pandas` uses and documented there: a sub-question is confined to one
    company and one year, so the slots are spent on that report's own statements
    rather than on near-duplicates from the years it is being compared against.
    """
    names, frames, _ = load_evidence(table_ids, config.selection_sub_tables)
    if not frames:
        return None
    solution, prompt, _ = await agenerate(
        question, frames, names, thinking=config.codegen_thinking
    )
    result = await aexecute(
        solution, prompt, frames, question=question,
        unit_hint="" if unit_from_hint(question) else _SUB_UNIT_HINT,
        names=names, max_repairs=config.max_repairs,
        repair_history=config.repair_history,
    )
    if result["diag"].get("failed") or degenerate_query(result["pandas_query"]):
        return None
    return {"value": float(result["answer"]), "frames": frames, "names": names,
            "prompt": prompt, "result": result}


__all__ = ["asub_value", "make_execute_and_repair", "make_generate_pandas"]
