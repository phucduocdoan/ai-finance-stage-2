"""Solver LangGraph node factories for the solve pipeline."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Mapping

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen.execute import aexecute
from finance_qa.modules.solve.facts.structured_facts import (
    StructuredFactError,
    asolve_structured_facts,
)
from finance_qa.modules.solve.pipeline.emit import emit_result, emit_solver_result
from finance_qa.modules.solve.pipeline.nodes.generate import asub_value
from finance_qa.modules.solve.pipeline.outcome import (
    answered,
    append_unique,
    declined,
    done_payload,
    errored,
)
from finance_qa.modules.solve.solvers.capability_router import capability_trace
from finance_qa.modules.solve.solvers.cell_locator import locate_single_cell
from finance_qa.modules.solve.solvers.decompose import (
    aplan,
    axis_of,
    pick,
    sub_question,
    tables_for,
    years_in_text,
)
from finance_qa.modules.solve.solvers.formula_facts import (
    FormulaFactError,
    asolve_formula_facts,
)
from finance_qa.modules.solve.solvers.raw_selection_linker import (
    RawSelectionError,
    aprepare_raw_selection_linker,
)
from finance_qa.modules.solve.solvers.raw_table_linker import (
    RawTableLinkError,
    aprepare_raw_table_linker,
)
from finance_qa.modules.solve.solvers.selection_facts import (
    SelectionFactError,
    asolve_selection_facts,
)


State = Mapping[str, Any]


def make_solve_selection(config: FinanceAgentConfig):
    """Answer a selection question by fanning out over its axis.

    Only the final stage is submitted. `build_submission` ships one
    `pandas_query` per question and the grader re-runs it, so the intermediates
    stay internal and the query that leaves here is an ordinary single-table
    expression at the winning element — which also keeps `evidence` pointing at
    exactly the table it reads. Everything the submission therefore cannot show
    goes to `diag["selection"]`.

    Any failure returns ``{}`` and the router sends the question down the
    unchanged path, so this node can only add answers, never remove them.
    """

    async def solve_selection(state: State) -> dict:
        axis_elements = axis_of(
            state["question"], state.get("years") or [], state.get("tickers") or []
        )
        if axis_elements is None:
            return {}
        axis, elements = axis_elements
        table_ids = list(state.get("table_ids") or [])
        errors = list(state.get("errors") or [])
        # The dimension the fan-out is *not* varying, so each sub-question still
        # names it. On a year axis that is the company; on a ticker axis, the year.
        if axis == "year":
            fixed = ", ".join(str(t) for t in (state.get("tickers") or []))
        else:
            named = sorted({int(y) for y in (state.get("years") or []) if y})
            named = named or sorted(years_in_text(state["question"]))
            fixed = str(named[0]) if named else ""

        try:
            plan = await aplan(state["question"], axis, elements)
        except Exception as exc:  # noqa: BLE001 - a failed plan is not a failed answer
            return declined(
                state, "selection", f"plan: {exc}",
                errors=[f"selection: plan: {exc}"],
            )

        # Ranking and filtering are both one metric per element, so they go out in
        # a single wave: the question's latency is one sub-question deep, not two.
        jobs = [("rank", element) for element in elements]
        if plan.filter_metric:
            jobs += [("filter", element) for element in elements]

        async def run(stage: str, element) -> dict | None:
            template = plan.rank_metric if stage == "rank" else plan.filter_metric
            text = sub_question(template, axis, element, fixed)
            tables = tables_for(table_ids, axis, element)
            if not text or not tables:
                return None
            try:
                return await asub_value(text, tables, config)
            except Exception:  # noqa: BLE001 - one dead element must not kill the fan-out
                return None

        values = await asyncio.gather(*(run(stage, el) for stage, el in jobs))
        scored: dict[str, dict] = {"rank": {}, "filter": {}}
        # The submission carries stage 5 only, so a flat score cannot say whether
        # the plan, one sub-query or the final read was what missed. The sub-query
        # and the table it read are the smallest thing that answers that.
        steps: list[dict] = []
        for (stage, element), got in zip(jobs, values):
            scored[stage][element] = None if got is None else got["value"]
            steps.append({
                "stage": stage, "element": str(element),
                "question": sub_question(
                    plan.rank_metric if stage == "rank" else plan.filter_metric,
                    axis, element, fixed,
                ),
                "value": None if got is None else got["value"],
                "query": "" if got is None else got["result"]["pandas_query"],
                "tables": [] if got is None else list(got["names"].values()),
            })

        winner, trace = pick(plan, axis, scored["rank"], scored["filter"])
        trace = {"axis": axis, "elements": [str(e) for e in elements],
                 "plan": plan.model_dump(), "steps": steps, **trace}
        if winner is None:
            reason = str(trace.get("reason") or "không chọn được")
            return declined(
                state, "selection", reason,
                payload=trace,
                errors=[f"selection: {reason}"],
            )

        final_text = sub_question(plan.answer_metric, axis, winner, fixed)
        final_tables = tables_for(table_ids, axis, winner)
        trace["answer_question"] = final_text
        if not final_text or not final_tables:
            reason = "không có bảng cho phần tử được chọn"
            return declined(
                state, "selection", reason,
                payload=trace,
                errors=[f"selection: {reason}"],
            )
        try:
            final = await asub_value(final_text, final_tables, config)
        except Exception as exc:  # noqa: BLE001
            reason = f"bước cuối: {exc}"
            return errored(
                state, "selection", reason,
                payload=trace,
                errors=[f"selection: {reason}"],
            )
        if final is None:
            reason = "bước cuối không ra số"
            return declined(
                state, "selection", reason,
                payload=trace,
                errors=[f"selection: {reason}"],
            )

        # `emit_result` reads `names` to rebuild evidence and `evidence_tables`
        # for diag, so it must see the winning element's tables rather than the
        # ones `generate_pandas` would have loaded — this node never ran it.
        trace = done_payload(trace)
        at_winner = {**state, "names": final["names"], "frames": final["frames"],
                     "evidence_tables": list(final["names"].values())}
        return {
            **emit_result(at_winner, final["result"], {"selection": trace}),
            "frames": final["frames"],
            "names": final["names"],
            "evidence_tables": list(final["names"].values()),
            "codegen_prompt": final["prompt"],
        }

    return solve_selection


async def _run_fact_solver(
    state: State,
    solver_name: str,
    solve: Callable[[State], Awaitable[dict]],
    decline_exc: type[Exception],
) -> dict:
    """Run a facts solver and translate its outcome into a node state update.

    `make_solve_structured_facts`, `make_solve_selection_facts` and
    `make_solve_formula_facts` below all share this exact shape: call an
    `asolve_*` function, decline on its own "this question isn't mine" error,
    fall back to `errored` on anything else, else report the fact-solver
    answer. What varies between them is only the solver name, the `asolve_*`
    call and its decline exception, so those are what callers parameterize.

    This branch never builds dataframe variables or a codegen prompt;
    `verify_answer` sees the empty prompt and becomes a pass-through.
    """
    errors = list(state.get("errors") or [])
    try:
        result = await solve(state)
    except decline_exc as exc:
        return declined(
            state, solver_name, str(exc),
            errors=[f"{solver_name}: {exc}"],
        )
    except Exception as exc:  # noqa: BLE001 - fallback is the product behaviour
        reason = f"{type(exc).__name__}: {exc}"
        return errored(
            state, solver_name, reason,
            errors=[f"{solver_name}: {reason}"],
        )

    return answered(
        state,
        solver_name,
        answer=result["answer"],
        pandas_query=result["pandas_query"],
        evidence=result["evidence"],
        table_ids=append_unique(list(state.get("table_ids") or []), result["table_ids"]),
        diag_payload=result["diag"],
        errors=errors,
        frames={},
        names={},
        evidence_tables=result["table_ids"],
        codegen_prompt="",
        solution={},
    )


def make_solve_structured_facts(config: FinanceAgentConfig):
    """Answer from normalized main-statement facts, falling back on any miss."""

    async def solve_structured_facts(state: State) -> dict:
        return await _run_fact_solver(
            state,
            "structured_facts",
            lambda s: asolve_structured_facts(
                s, planner_thinking=config.structured_facts_planner_thinking,
            ),
            StructuredFactError,
        )

    return solve_structured_facts


def make_solve_selection_facts(config: FinanceAgentConfig):
    """Answer deterministic selection questions from structured facts."""

    async def solve_selection_facts(state: State) -> dict:
        return await _run_fact_solver(
            state, "selection_facts", asolve_selection_facts, SelectionFactError,
        )

    return solve_selection_facts


def make_solve_formula_facts(config: FinanceAgentConfig):
    """Answer simple catalog formulae from normalized facts, else fall back."""

    async def solve_formula_facts(state: State) -> dict:
        return await _run_fact_solver(
            state,
            "formula_facts",
            lambda s: asolve_formula_facts(
                s, planner_thinking=config.formula_facts_planner_thinking,
            ),
            FormulaFactError,
        )

    return solve_formula_facts


async def _run_linked_solver(
    state: State,
    solver_name: str,
    prepare: Callable[[State], Awaitable[dict]],
    decline_exc: type[Exception],
    *,
    merge_table_ids: bool = False,
) -> dict:
    """Run a raw-table-linked solver: prepare a solution, execute it, translate outcome.

    `make_solve_raw_table_linker` and `make_solve_raw_selection_linker` below
    share this exact shape: call an `aprepare_*` function, decline on its own
    "this question isn't mine" error, execute the resulting solution, decline
    again if the query itself failed, else report the solver's answer. What
    varies between them is only the solver name, the `aprepare_*` call, its
    decline exception, and whether `table_ids` gets merged with the state's
    existing ones before emitting.
    """
    try:
        prepared = await prepare(state)
    except decline_exc as exc:
        return declined(
            state, solver_name, str(exc),
            errors=[f"{solver_name}: {exc}"],
        )
    except Exception as exc:  # noqa: BLE001 - fallback is product behaviour
        reason = f"{type(exc).__name__}: {exc}"
        return errored(
            state, solver_name, reason,
            errors=[f"{solver_name}: {reason}"],
        )

    result = await aexecute(
        prepared["solution"],
        "",
        prepared["frames"],
        question=state["question"],
        unit_hint=state.get("unit_hint") or "",
        names=prepared["names"],
        tickers=state.get("tickers") or [],
        max_repairs=0,
        repair_history=False,
    )
    if result["diag"].get("failed"):
        return declined(
            state, solver_name, "query failed",
            payload=prepared["diag"],
            errors=[f"{solver_name}: {err}" for err in result["errors"]],
        )

    extra = {}
    if merge_table_ids:
        extra["table_ids"] = append_unique(list(state.get("table_ids") or []), prepared["table_ids"])
    return emit_solver_result(
        state,
        solver_name,
        result,
        prepared["diag"],
        frames=prepared["frames"],
        names=prepared["names"],
        evidence_tables=prepared["table_ids"],
        solution=prepared["solution"].model_dump(),
        codegen_prompt="",
        **extra,
    )


def make_solve_raw_table_linker(config: FinanceAgentConfig):
    """Answer fixed-scope raw-table arithmetic from linked cell candidates."""

    async def solve_raw_table_linker(state: State) -> dict:
        return await _run_linked_solver(
            state,
            "raw_table_linker",
            lambda s: aprepare_raw_table_linker(
                s,
                use_planner=config.raw_table_linker_planner,
                planner_thinking=config.raw_table_linker_planner_thinking,
                use_ratio_groups=config.raw_table_linker_ratio_groups,
            ),
            RawTableLinkError,
        )

    return solve_raw_table_linker


def make_solve_raw_selection_linker(config: FinanceAgentConfig):
    """Answer raw-table max/min selection with bounded candidate ids."""

    async def solve_raw_selection_linker(state: State) -> dict:
        return await _run_linked_solver(
            state,
            "raw_selection_linker",
            lambda s: aprepare_raw_selection_linker(
                s,
                use_planner=config.raw_table_linker_planner,
                planner_thinking=config.raw_table_linker_planner_thinking,
            ),
            RawSelectionError,
            merge_table_ids=True,
        )

    return solve_raw_selection_linker


def make_trace_capabilities(config: FinanceAgentConfig):
    """Record the cheap capability routing decision without changing behavior."""

    def trace_capabilities(state: State) -> dict:
        return {
            "diag": {
                **(state.get("diag") or {}),
                "capability_router": capability_trace(
                    state,
                    cell_locator=config.cell_locator,
                    formula_facts=config.formula_facts,
                    raw_table_linker=config.raw_table_linker,
                    selection_facts=config.selection_facts,
                    raw_selection_linker=config.raw_selection_linker,
                    structured_facts=config.structured_facts,
                    selection_decompose=config.selection_decompose,
                ),
            },
        }

    return trace_capabilities


def make_solve_single_cell(config: FinanceAgentConfig):
    """Try a high-confidence deterministic cell read, otherwise fall back."""

    async def solve_single_cell(state: State) -> dict:
        if not config.cell_locator:
            return {}
        hit, diag = locate_single_cell(
            state,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
        )
        if hit is None:
            return declined(
                state, "cell_locator", str(diag.get("reason") or "no located cell"),
                payload=diag,
            )

        names = {"df1": hit.table_id}
        try:
            frames = {"df1": load_frame(hit.table_id)}
            solution = hit.solution("df1")
            result = await aexecute(
                solution,
                "",
                frames,
                question=state["question"],
                unit_hint=state.get("unit_hint") or "",
                names=names,
                tickers=state.get("tickers") or [],
                max_repairs=0,
                repair_history=False,
            )
        except Exception as exc:  # noqa: BLE001 - fallback is the product behaviour
            reason = f"{type(exc).__name__}: {exc}"
            return errored(
                state, "cell_locator", reason,
                payload=diag,
                errors=[f"cell_locator: {reason}"],
            )
        if result["diag"].get("failed"):
            return declined(
                state, "cell_locator", "query failed",
                payload=diag,
                errors=[f"cell_locator: {err}" for err in result["errors"]],
            )

        # verify_answer needs a prompt to revise; this branch has no prompt
        # and should pass through after `emit_result`.
        return emit_solver_result(
            state,
            "cell_locator",
            result,
            diag,
            frames=frames,
            names=names,
            evidence_tables=[hit.table_id],
            solution=solution.model_dump(),
            codegen_prompt="",
        )

    return solve_single_cell


__all__ = [
    "make_solve_formula_facts",
    "make_solve_raw_selection_linker",
    "make_solve_raw_table_linker",
    "make_solve_selection",
    "make_solve_selection_facts",
    "make_solve_single_cell",
    "make_solve_structured_facts",
    "make_trace_capabilities",
]
