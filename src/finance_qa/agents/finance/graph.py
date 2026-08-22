"""The grounded-codegen pipeline: four nodes, one LLM call each.

Topology:
  understand → retrieve → generate_pandas → execute_and_repair → verify_answer → END
                       ↘ solve_selection ↗ (and back to generate_pandas on failure)

One path for every question, with one exception that earns its branch: a
question whose answer is a *choice* between years or between companies, which
needs several cells resolved before the target cell is even known. Everything
else keeps the single path, so a failure is still attributable to a node rather
than to which of six routes it happened to take. The branch is gated on a
surface marker plus an axis of at least two elements and falls back to the same
path whenever any stage of it comes up empty — see `selection_decompose`.

`understand` stays in front because retrieval hard-filters candidates on ticker /
year / doc_type and those come from it — the node that lifted DOCS_F2MACRO from
0.9248 to 0.9537. It is question understanding, not table understanding.

There is deliberately no evidence-selection step. It used to be its own node; it is
now a `[:codegen_max_tables]` slice of retrieval's ranking inside `generate_pandas`
(interleaved and widened first when the question names a period or several
companies — see `codegen_budget`), because that is all it ever was. Choosing which of those tables to read is part of
the call that writes the query — one decision by the one model that can see the
contents, instead of two decisions where the first was made blind.

What actually cost answers was not the slice but the schema: `target_row` /
`target_column` are singular, so the model answered every question with one cell,
including the 12 that compare two companies (0/12 correct). Letting the expression
span cells and dataframes took the "needs several cells" bucket from 0/13 to 5/13
and the whole gold set from 28/73 to 33/73, with queries reading more than one
dataframe going from 3/75 to 17/75. Widening the slice on top of that did *not*
help — see `codegen_max_tables`.

Loading does not narrow `state["table_ids"]`, which is what gets submitted:
retrieval is scored on its own F2, so dropping tables the query did not read
would throw away recall. It can *grow* it — a table `find_rows` surfaced and the
final query actually reads is added in `_emit`, because evidence pointing at a
CSV outside `relevant_tables` is not a valid submission item.

State is `FinanceState` plus two internal keys, so `scripts/build_submission.py`
and `submission_item()` consume this flow's records unchanged.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping

from langgraph.graph import END, StateGraph

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.state import FinanceState
from finance_qa.agents.finance.retrieve import make_retrieve_node
from finance_qa.agents.finance.understand import make_understand
from finance_qa.agents.finance.utils import slot_round_robin, year_round_robin
from finance_qa.core.http import run_sync
from finance_qa.modules.data.service import ordered_table_names
from finance_qa.modules.data.table_store import load_frame, submission_csv_name
from finance_qa.modules.solve.codegen.codegen import agenerate, build_prompt
from finance_qa.modules.solve.codegen.execute import aexecute
from finance_qa.modules.solve.codegen.screening import agenerate_screening
from finance_qa.modules.solve.codegen.verify import arevise, averify
from finance_qa.modules.solve.common.screening import is_screening
from finance_qa.modules.solve.common.solution import PandasSolution
from finance_qa.modules.solve.common.units import unit_from_hint
from finance_qa.modules.solve.facts.profile_validate import validate_profile_selection
from finance_qa.modules.solve.facts.structured_facts import (
    StructuredFactError,
    asolve_structured_facts,
)
from finance_qa.modules.solve.solvers.capability_router import capability_trace
from finance_qa.modules.solve.solvers.cell_locator import locate_single_cell
from finance_qa.modules.solve.solvers.decompose import (
    aplan,
    axis_of,
    degenerate_query,
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


_DF_VAR = re.compile(r"\bdf\d+\b")


class SolveState(FinanceState, total=False):
    """`FinanceState` plus what the solve nodes hand each other.

    `codegen_prompt` is carried so the repair call can re-show the same grids
    instead of guessing, and both keys are dropped from the record written by the
    runner (the prompt is a few thousand chars per question).
    """

    evidence_tables: list[str]   # the tables codegen was shown
    codegen_prompt: str
    solution: dict[str, Any]


def load_evidence(table_ids: list[str], max_tables: int) -> tuple[dict, dict, list[str]]:
    """Load the head `max_tables` tables of retrieval's ranking as df1, df2, ...

    Returns ``(names, frames, errors)``. Duplicate ids are collapsed because the
    judge's picks and the primary-statement tail overlap, and a table that will
    not load is dropped from the variables rather than shipped as evidence
    pointing at a frame no query can read.
    """
    errors: list[str] = []
    ordered = list(dict.fromkeys(table_ids))[:max_tables]
    names = ordered_table_names(ordered)
    frames: dict[str, Any] = {}
    for var, table_id in names.items():
        try:
            frames[var] = load_frame(table_id)
        except Exception as exc:  # noqa: BLE001 - reported, run continues
            errors.append(f"load: {table_id} -> {exc}")
    return {var: tid for var, tid in names.items() if var in frames}, frames, errors


def codegen_budget(
    state: Mapping[str, Any], config: FinanceAgentConfig
) -> tuple[list[str], int]:
    """`(table_ids in load order, how many to load)` for one question.

    A question that names several companies or several years is the only kind
    that can run out of slots before it runs out of relevance, so it is the only
    kind that gets more of them — and it needs its ids interleaved, because
    ranking alone puts the third company's table at position 14.

    Companies are checked first: a question naming both several companies and
    several years (85 of the 310 multi-ticker questions) needs a table per
    (ticker, year) pair, which is what `slot_round_robin` spreads and what the
    multi-company budget is sized for. `year_round_robin` would interleave only
    the years and leave the companies to the ranking.
    """
    table_ids = list(state.get("table_ids") or [])
    tickers = list(state.get("tickers") or [])
    years = list(state.get("years") or [])
    if len(tickers) >= 2:
        needed = len(tickers) * max(len(years), 1)
        cap = config.codegen_max_tables_multi_company
        # `config.py` (codegen_max_tables_multi_company) measured this widening
        # alone as flat: coverage went 310/310 and score stayed 4/38, because a
        # single pandas expression has nowhere to put a filter. That is what
        # `screening_solver` (screening.py) adds, so once it is on this pairs the
        # wider budget with something for the extra companies to be filtered by.
        if config.screening_solver and is_screening(str(state.get("question") or "")):
            cap = 12
        return (
            slot_round_robin(table_ids),
            max(config.codegen_max_tables, min(needed, cap)),
        )
    if state.get("multi_year"):
        return year_round_robin(table_ids), config.codegen_max_tables_multi_year
    return table_ids, config.codegen_max_tables


def make_generate_pandas(config: FinanceAgentConfig):
    async def generate_pandas(state: SolveState) -> dict:
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
    async def execute_and_repair(state: SolveState) -> dict:
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
        return _emit(state, result)

    return execute_and_repair


def _emit(state: SolveState, result: dict, extra_diag: dict | None = None) -> dict:
    """Turn an `aexecute` result into the state update both solve nodes return."""
    final = result["solution"]
    # Evidence must list exactly the variables the query reads, or the submission
    # validator rejects the item. Rebuilt from `names` rather than filtered from
    # `state["evidence"]`, because by the time verify_answer runs that list has
    # already been narrowed to the *previous* query's variables — a revision that
    # switches to another table would then ship without it (13 of 73 items).
    names = state.get("names") or {}
    everything = [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in names.items()
    ] or list(state.get("evidence") or [])
    # `\bdfN\b`, not `in`: a substring test reads df1 as used by `df10`, which was
    # harmless at 3 variables and is not once `find_rows` can bind more than nine.
    read = set(_DF_VAR.findall(result["pandas_query"]))
    used = [ev for ev in everything if ev["variable"] in read]
    # A table the query reads must also be submitted, or `evidence` points at a
    # CSV missing from `relevant_tables`. Only the ones actually read: retrieval
    # is scored on its own F2, and appending every table a lookup touched would
    # dilute it.
    table_ids = list(state.get("table_ids") or [])
    table_ids += [names[ev["variable"]] for ev in used
                  if names.get(ev["variable"]) and names[ev["variable"]] not in table_ids]
    return {
        "answer": float(result["answer"]),
        "pandas_query": result["pandas_query"],
        "evidence": used or list(state.get("evidence") or []),
        "table_ids": table_ids,
        "solver": "codegen",
        "solution": final.model_dump(),
        "errors": list(state.get("errors") or []) + result["errors"],
        "diag": {
            **(state.get("diag") or {}),
            "units": result["diag"],
            "target_row": final.target_row,
            "target_column": final.target_column,
            "table_variable": final.table_variable,
            "evidence_tables": list(state.get("evidence_tables") or []),
            **(extra_diag or {}),
        },
    }


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


async def _asub_value(
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

    async def solve_selection(state: SolveState) -> dict:
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
            return {"errors": errors + [f"selection: plan: {exc}"]}

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
                return await _asub_value(text, tables, config)
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
            return {"errors": errors + [f"selection: {trace.get('reason', 'không chọn được')}"],
                    "diag": {**(state.get("diag") or {}), "selection": trace}}

        final_text = sub_question(plan.answer_metric, axis, winner, fixed)
        final_tables = tables_for(table_ids, axis, winner)
        trace["answer_question"] = final_text
        if not final_text or not final_tables:
            return {"errors": errors + ["selection: không có bảng cho phần tử được chọn"],
                    "diag": {**(state.get("diag") or {}), "selection": trace}}
        try:
            final = await _asub_value(final_text, final_tables, config)
        except Exception as exc:  # noqa: BLE001
            return {"errors": errors + [f"selection: bước cuối: {exc}"],
                    "diag": {**(state.get("diag") or {}), "selection": trace}}
        if final is None:
            return {"errors": errors + ["selection: bước cuối không ra số"],
                    "diag": {**(state.get("diag") or {}), "selection": trace}}

        # `_emit` reads `names` to rebuild evidence and `evidence_tables` for diag,
        # so it must see the winning element's tables rather than the ones
        # `generate_pandas` would have loaded — this node never ran it.
        trace["done"] = True
        at_winner = {**state, "names": final["names"], "frames": final["frames"],
                     "evidence_tables": list(final["names"].values())}
        return {
            **_emit(at_winner, final["result"], {"selection": trace}),
            "frames": final["frames"],
            "names": final["names"],
            "evidence_tables": list(final["names"].values()),
            "codegen_prompt": final["prompt"],
        }

    return solve_selection


def make_solve_structured_facts(config: FinanceAgentConfig):
    """Answer from normalized main-statement facts, falling back on any miss."""

    async def solve_structured_facts(state: SolveState) -> dict:
        errors = list(state.get("errors") or [])
        try:
            result = await asolve_structured_facts(
                state,
                planner_thinking=config.structured_facts_planner_thinking,
            )
        except StructuredFactError as exc:
            return {
                "errors": errors + [f"structured_facts: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "structured_facts": {"done": False, "reason": str(exc)},
                },
            }
        except Exception as exc:  # noqa: BLE001 - fallback is the product behaviour
            return {
                "errors": errors + [f"structured_facts: {type(exc).__name__}: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "structured_facts": {
                        "done": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                    },
                },
            }

        table_ids = list(state.get("table_ids") or [])
        for table_id in result["table_ids"]:
            if table_id not in table_ids:
                table_ids.append(table_id)
        return {
            "answer": result["answer"],
            "pandas_query": result["pandas_query"],
            "evidence": result["evidence"],
            "table_ids": table_ids,
            "solver": "structured_facts",
            "errors": errors,
            "diag": {
                **(state.get("diag") or {}),
                "structured_facts": result["diag"],
            },
            # This branch does not build dataframe variables or a codegen prompt.
            # verify_answer sees the empty prompt and becomes a pass-through.
            "frames": {},
            "names": {},
            "evidence_tables": result["table_ids"],
            "codegen_prompt": "",
            "solution": {},
        }

    return solve_structured_facts


def make_solve_selection_facts(config: FinanceAgentConfig):
    """Answer deterministic selection questions from structured facts."""

    async def solve_selection_facts(state: SolveState) -> dict:
        errors = list(state.get("errors") or [])
        try:
            result = await asolve_selection_facts(state)
        except SelectionFactError as exc:
            return {
                "errors": errors + [f"selection_facts: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "selection_facts": {"done": False, "reason": str(exc)},
                },
            }
        except Exception as exc:  # noqa: BLE001 - fallback is product behaviour
            return {
                "errors": errors + [f"selection_facts: {type(exc).__name__}: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "selection_facts": {
                        "done": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                    },
                },
            }

        table_ids = list(state.get("table_ids") or [])
        for table_id in result["table_ids"]:
            if table_id not in table_ids:
                table_ids.append(table_id)
        return {
            "answer": result["answer"],
            "pandas_query": result["pandas_query"],
            "evidence": result["evidence"],
            "table_ids": table_ids,
            "solver": "selection_facts",
            "errors": errors,
            "diag": {
                **(state.get("diag") or {}),
                "selection_facts": result["diag"],
            },
            "frames": {},
            "names": {},
            "evidence_tables": result["table_ids"],
            "codegen_prompt": "",
            "solution": {},
        }

    return solve_selection_facts


def make_solve_formula_facts(config: FinanceAgentConfig):
    """Answer simple catalog formulae from normalized facts, else fall back."""

    async def solve_formula_facts(state: SolveState) -> dict:
        errors = list(state.get("errors") or [])
        try:
            result = await asolve_formula_facts(
                state,
                planner_thinking=config.formula_facts_planner_thinking,
            )
        except FormulaFactError as exc:
            return {
                "errors": errors + [f"formula_facts: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "formula_facts": {"done": False, "reason": str(exc)},
                },
            }
        except Exception as exc:  # noqa: BLE001 - fallback is the product behaviour
            return {
                "errors": errors + [f"formula_facts: {type(exc).__name__}: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "formula_facts": {
                        "done": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                    },
                },
            }

        table_ids = list(state.get("table_ids") or [])
        for table_id in result["table_ids"]:
            if table_id not in table_ids:
                table_ids.append(table_id)
        return {
            "answer": result["answer"],
            "pandas_query": result["pandas_query"],
            "evidence": result["evidence"],
            "table_ids": table_ids,
            "solver": "formula_facts",
            "errors": errors,
            "diag": {
                **(state.get("diag") or {}),
                "formula_facts": result["diag"],
            },
            "frames": {},
            "names": {},
            "evidence_tables": result["table_ids"],
            "codegen_prompt": "",
            "solution": {},
        }

    return solve_formula_facts


def make_solve_raw_table_linker(config: FinanceAgentConfig):
    """Answer fixed-scope raw-table arithmetic from linked cell candidates."""

    async def solve_raw_table_linker(state: SolveState) -> dict:
        errors = list(state.get("errors") or [])
        try:
            prepared = await aprepare_raw_table_linker(
                state,
                use_planner=config.raw_table_linker_planner,
                planner_thinking=config.raw_table_linker_planner_thinking,
                use_ratio_groups=config.raw_table_linker_ratio_groups,
            )
        except RawTableLinkError as exc:
            return {
                "errors": errors + [f"raw_table_linker: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "raw_table_linker": {"done": False, "reason": str(exc)},
                },
            }
        except Exception as exc:  # noqa: BLE001 - fallback is product behaviour
            return {
                "errors": errors + [f"raw_table_linker: {type(exc).__name__}: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "raw_table_linker": {
                        "done": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                    },
                },
            }

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
            return {
                "errors": errors + [f"raw_table_linker: {err}" for err in result["errors"]],
                "diag": {
                    **(state.get("diag") or {}),
                    "raw_table_linker": {
                        **prepared["diag"],
                        "done": False,
                        "reason": "query failed",
                    },
                },
            }

        at_raw = {
            **state,
            "names": prepared["names"],
            "frames": prepared["frames"],
            "evidence_tables": prepared["table_ids"],
            "solution": prepared["solution"].model_dump(),
        }
        emitted = _emit(at_raw, result, {"raw_table_linker": prepared["diag"]})
        return {
            **emitted,
            "solver": "raw_table_linker",
            "frames": prepared["frames"],
            "names": prepared["names"],
            "evidence_tables": prepared["table_ids"],
            "codegen_prompt": "",
        }

    return solve_raw_table_linker


def make_solve_raw_selection_linker(config: FinanceAgentConfig):
    """Answer raw-table max/min selection with bounded candidate ids."""

    async def solve_raw_selection_linker(state: SolveState) -> dict:
        errors = list(state.get("errors") or [])
        try:
            prepared = await aprepare_raw_selection_linker(
                state,
                use_planner=config.raw_table_linker_planner,
                planner_thinking=config.raw_table_linker_planner_thinking,
            )
        except RawSelectionError as exc:
            return {
                "errors": errors + [f"raw_selection_linker: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "raw_selection_linker": {"done": False, "reason": str(exc)},
                },
            }
        except Exception as exc:  # noqa: BLE001 - fallback is product behaviour
            return {
                "errors": errors + [f"raw_selection_linker: {type(exc).__name__}: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "raw_selection_linker": {
                        "done": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                    },
                },
            }

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
            return {
                "errors": errors + [f"raw_selection_linker: {err}" for err in result["errors"]],
                "diag": {
                    **(state.get("diag") or {}),
                    "raw_selection_linker": {
                        **prepared["diag"],
                        "done": False,
                        "reason": "query failed",
                    },
                },
            }

        table_ids = list(state.get("table_ids") or [])
        for table_id in prepared["table_ids"]:
            if table_id not in table_ids:
                table_ids.append(table_id)
        at_raw = {
            **state,
            "table_ids": table_ids,
            "names": prepared["names"],
            "frames": prepared["frames"],
            "evidence_tables": prepared["table_ids"],
            "solution": prepared["solution"].model_dump(),
        }
        emitted = _emit(at_raw, result, {"raw_selection_linker": prepared["diag"]})
        return {
            **emitted,
            "solver": "raw_selection_linker",
            "frames": prepared["frames"],
            "names": prepared["names"],
            "evidence_tables": prepared["table_ids"],
            "codegen_prompt": "",
        }

    return solve_raw_selection_linker


def make_trace_capabilities(config: FinanceAgentConfig):
    """Record the cheap capability routing decision without changing behavior."""

    def trace_capabilities(state: SolveState) -> dict:
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

    async def solve_single_cell(state: SolveState) -> dict:
        if not config.cell_locator:
            return {}
        hit, diag = locate_single_cell(
            state,
            table_ids=list(state.get("table_ids") or []),
            shortlist=list(state.get("shortlist") or []),
        )
        if hit is None:
            return {"diag": {**(state.get("diag") or {}), "cell_locator": diag}}

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
            return {
                "errors": list(state.get("errors") or []) + [f"cell_locator: {type(exc).__name__}: {exc}"],
                "diag": {
                    **(state.get("diag") or {}),
                    "cell_locator": {**diag, "done": False, "reason": f"{type(exc).__name__}: {exc}"},
                },
            }
        if result["diag"].get("failed"):
            return {
                "errors": list(state.get("errors") or []) + [f"cell_locator: {err}" for err in result["errors"]],
                "diag": {
                    **(state.get("diag") or {}),
                    "cell_locator": {**diag, "done": False, "reason": "query failed"},
                },
            }

        at_hit = {
            **state,
            "names": names,
            "frames": frames,
            "evidence_tables": [hit.table_id],
            "solution": solution.model_dump(),
        }
        emitted = _emit(at_hit, result, {"cell_locator": diag})
        return {
            **emitted,
            "solver": "cell_locator",
            "frames": frames,
            "names": names,
            "evidence_tables": [hit.table_id],
            # verify_answer needs a prompt to revise; this branch has no prompt
            # and should pass through after `_emit`.
            "codegen_prompt": "",
        }

    return solve_single_cell


# The narrow solvers (cell_locator, formula_facts, raw_table_linker,
# selection_facts, raw_selection_linker, structured_facts) each say, in their own
# comment, that they leave `codegen_prompt` empty so verify_answer passes
# through — which meant diag["verify"] was empty for every one of them. Measured
# on a full 1012-question run: present for 495 of 520 codegen answers, 0 of 492
# answers from the other five solvers combined, so half the corpus carried no
# quality signal at all. True keeps that half a *measurement* only: `averify`
# runs and diag["verify"] gets filled in, but `arevise` never does, because none
# of those solvers build the table_ids/evidence bookkeeping a kept revision
# would need — a revision that silently miswrote that would ship a wrong answer
# instead of falling back, which is what happens on the codegen path below.
VERIFY_NARROW_SOLVERS_OBSERVE_ONLY = True


def make_verify_answer(config: FinanceAgentConfig):
    """Check the cell the query read, and rewrite the query once if it is wrong.

    This is the only node that can reach the largest failure bucket. Repair fires
    on exceptions, and a query that reads the wrong row raises none: measured on
    the 73 gold questions, 5 queries threw and ~34 returned a clean wrong number.

    Two guards keep a check that is itself a model call from costing more than it
    wins. The rewrite is kept only when it executes *and* moves the answer, so a
    revision that dies falls back to the original instead of shipping 0.0; and
    there is exactly one round, with no re-verification of the rewrite, because a
    verifier that can veto its own replacement will loop on the questions where it
    is the one that is wrong.
    """

    async def verify_answer(state: SolveState) -> dict:
        query = state.get("pandas_query") or ""
        frames = state.get("frames") or {}
        names = state.get("names") or {}
        prompt = state.get("codegen_prompt") or ""
        drop = {"codegen_prompt": ""}  # prompt text, not a result
        if not config.verify_answer:
            return drop
        # A query that never ran has no cell to check, and the verifier shown one
        # reads the 0.0 as an answer and approves it (qid280). Repair already had
        # three attempts at this one; a fourth under a different prompt is not a
        # different idea.
        if (state.get("diag") or {}).get("units", {}).get("failed"):
            return drop

        # A screening answer is checked but never rewritten. `arevise` submits a
        # `PandasSolution`, which by construction cannot hold a filter, so the
        # only rewrite it can offer is the flat shape this class already fails
        # at — and the rewrite is kept on "it executed", not on "it is more
        # right". Measured on the first flag-on run of the 29 labelled screening
        # questions: `compose` produced a `pd.Series` plan for 19 of them and
        # only 3 survived to the record, the other 16 having been revised back
        # into a single expression with no execution error to justify it. With
        # `SOLVE_VERIFY_ANSWER=0` the plan survived on 3 of 4 spot-checked ids.
        screening = bool((state.get("diag") or {}).get("screening_solver"))
        # A narrow solver never built a codegen prompt (see the comment above),
        # so there is nothing to show the checker unless one is built here — the
        # same question + evidence grids codegen would have shown, empty for the
        # three solvers (formula_facts, selection_facts, structured_facts) that
        # answer from the fact catalog rather than a loaded table.
        narrow = not prompt
        if narrow:
            if not VERIFY_NARROW_SOLVERS_OBSERVE_ONLY or not query:
                return drop
            if not frames:
                # Those three solvers leave `frames`/`names` at `{}` (see their
                # own returns above), so without this the checker was shown a
                # bare question and no table at all — it judged qid18 (gold
                # 2077.87) wrong for a right answer, because it had nothing to
                # check the number against. Loaded the same way `generate_pandas`
                # does, from the ids the solver actually used rather than a new
                # limit, so the grids match what produced the answer.
                evidence_ids = state.get("evidence_tables") or state.get("table_ids") or []
                _, max_tables = codegen_budget(state, config)
                names, frames, _ = load_evidence(evidence_ids, max_tables)
                if not frames:
                    # Nothing to show the checker even after trying to load it —
                    # a verdict here would be the verifier grading a blank page,
                    # so the signal is recorded as missing rather than negative.
                    return {
                        **drop,
                        "diag": {
                            **(state.get("diag") or {}),
                            "verify": {"skipped": "no_evidence"},
                        },
                    }
            prompt = build_prompt(state["question"], frames, names)
        elif not frames or not prompt:
            return drop

        try:
            verdict, _ = await averify(
                prompt, query, float(state.get("answer") or 0.0),
                frames, names, unit_hint=state.get("unit_hint") or "",
            )
        except Exception as exc:  # noqa: BLE001 - a failed check is not a failed answer
            return {**drop, "errors": list(state.get("errors") or []) + [f"verify: {exc}"]}

        if narrow or screening:
            # Observe-only: record the verdict, never touch the answer.
            return {
                **drop,
                "diag": {
                    **(state.get("diag") or {}),
                    "verify": {"correct": verdict.correct, "reason": verdict.reason},
                },
            }

        if verdict.correct:
            return {**drop, "diag": {**(state.get("diag") or {}), "verify": {"correct": True}}}

        diag = {"verify": {"correct": False, "reason": verdict.reason, "before": query}}
        try:
            revised = await arevise(prompt, query, verdict.reason)
            result = await aexecute(
                revised, prompt, frames,
                question=state["question"], unit_hint=state.get("unit_hint") or "",
                names=names, tickers=state.get("tickers") or [],
                max_repairs=config.max_repairs,
                repair_history=config.repair_history,
            )
        except Exception as exc:  # noqa: BLE001
            return {**drop, "errors": list(state.get("errors") or []) + [f"revise: {exc}"]}
        if result["diag"].get("failed"):
            return {**drop, "diag": {**(state.get("diag") or {}), **diag, "verify_kept": False}}
        return {**_emit(state, result, {**diag, "verify_kept": True}), **drop}

    return verify_answer


def make_profile_validate(config: FinanceAgentConfig):
    """Attach TableProfile-based diagnostics to the final answer state."""

    def profile_validate(state: SolveState) -> dict:
        if not config.profile_validate:
            return {}
        try:
            diag = validate_profile_selection(
                state,
                frames=state.get("frames") or {},
                names=state.get("names") or {},
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics must not change answers
            diag = {
                "done": False,
                "reason": f"{type(exc).__name__}: {exc}",
                "query_cells": [],
                "findings": [],
                "summary": {"strong": 0, "weak": 0, "info": 0},
            }
        return {
            "diag": {
                **(state.get("diag") or {}),
                "profile_validate": diag,
            },
        }

    return profile_validate


def selection_route(config: FinanceAgentConfig, state: SolveState) -> str:
    """Shared fallback once every enabled solver in `SOLVER_CHAIN` has declined.

    Does not fit the chain below: it is gated on an axis found in the question,
    not on a flag plus a diag `done`, so it stays its own function rather than a
    row in the table.
    """
    if not config.selection_decompose:
        return "generate_pandas"
    axis = axis_of(
        state["question"], state.get("years") or [], state.get("tickers") or []
    )
    return "solve_selection" if axis else "generate_pandas"


# Solver chain in evaluation order: (config flag, node, diag key). Every
# `route_after_*` this replaces was the same shape repeated with one more
# `if config.X: return "solve_x"` appended — check whether the node that just
# ran declared its own diag key `done`, and if not, try the next enabled flag
# in this order, falling through to `selection_route` once the table is
# exhausted. `make_solver_router` walks this table instead of re-deriving the
# chain in each function; the trigger stays as narrow as `route_after_retrieve`
# used to document: everything a stage does not claim reaches `generate_pandas`
# over an unchanged path, so a regression elsewhere cannot be this branch's doing
# — that is what made the program-of-thought A/B attributable when it lost 11
# points by changing the prompt for all 94 questions instead of a subset.
SOLVER_CHAIN: list[tuple[str, str, str]] = [
    ("cell_locator", "solve_single_cell", "cell_locator"),
    ("formula_facts", "solve_formula_facts", "formula_facts"),
    ("raw_table_linker", "solve_raw_table_linker", "raw_table_linker"),
    ("selection_facts", "solve_selection_facts", "selection_facts"),
    ("raw_selection_linker", "solve_raw_selection_linker", "raw_selection_linker"),
    ("structured_facts", "solve_structured_facts", "structured_facts"),
]


def make_solver_router(config: FinanceAgentConfig, after: str | None):
    """Build the router that runs after `after` (or, if `None`, after retrieval).

    Returns `(route, destinations)`: `route` is the conditional-edge function,
    `destinations` the node list `add_conditional_edges` needs to validate it.
    `after=None` is the entry point, where nothing has run yet so there is no
    "did I just succeed" check before trying the first enabled flag.
    """
    start = 0
    diag_key = None
    if after is not None:
        start = 1 + next(i for i, (_, node, _) in enumerate(SOLVER_CHAIN) if node == after)
        diag_key = next(key for _, node, key in SOLVER_CHAIN if node == after)
    remaining = SOLVER_CHAIN[start:]

    def route(state: SolveState) -> str:
        if diag_key is not None and (state.get("diag") or {}).get(diag_key, {}).get("done"):
            return "verify_answer"
        for flag, node, _ in remaining:
            if getattr(config, flag):
                return node
        return selection_route(config, state)

    destinations = [node for _, node, _ in remaining] + ["solve_selection", "generate_pandas"]
    if after is not None:
        destinations = ["verify_answer"] + destinations
    return route, destinations


def route_after_selection(state: SolveState) -> str:
    """Fall through to the normal path whenever the fan-out did not answer.

    Does not fit `SOLVER_CHAIN` either: `solve_selection` is not gated on a flag
    checked in order, and on a miss it falls straight to `generate_pandas`
    without consulting `selection_route` again — this node is what
    `selection_route` sent the question to in the first place.
    """
    done = (state.get("diag") or {}).get("selection", {}).get("done")
    return "verify_answer" if done else "generate_pandas"


def build_graph(config: FinanceAgentConfig | None = None) -> StateGraph:
    config = config or FinanceAgentConfig()

    g = StateGraph(SolveState)
    g.add_node("understand", make_understand(config))
    g.add_node("retrieve", make_retrieve_node(config))
    g.add_node("trace_capabilities", make_trace_capabilities(config))
    g.add_node("solve_single_cell", make_solve_single_cell(config))
    g.add_node("solve_formula_facts", make_solve_formula_facts(config))
    g.add_node("solve_raw_table_linker", make_solve_raw_table_linker(config))
    g.add_node("solve_selection_facts", make_solve_selection_facts(config))
    g.add_node("solve_raw_selection_linker", make_solve_raw_selection_linker(config))
    g.add_node("solve_structured_facts", make_solve_structured_facts(config))
    g.add_node("solve_selection", make_solve_selection(config))
    g.add_node("generate_pandas", make_generate_pandas(config))
    g.add_node("execute_and_repair", make_execute_and_repair(config))
    g.add_node("verify_answer", make_verify_answer(config))
    g.add_node("profile_validate", make_profile_validate(config))

    g.set_entry_point("understand")
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve", "trace_capabilities")
    for after in [None, "solve_single_cell", "solve_formula_facts", "solve_raw_table_linker",
                  "solve_selection_facts", "solve_raw_selection_linker", "solve_structured_facts"]:
        route, destinations = make_solver_router(config, after)
        g.add_conditional_edges(after or "trace_capabilities", route, destinations)
    g.add_conditional_edges("solve_selection", route_after_selection,
                            ["verify_answer", "generate_pandas"])
    g.add_edge("generate_pandas", "execute_and_repair")
    g.add_edge("execute_and_repair", "verify_answer")
    g.add_edge("verify_answer", "profile_validate")
    g.add_edge("profile_validate", END)
    return g


def make_initial_state(question_id: int, question: str) -> SolveState:
    return {
        "id": question_id,
        "question": question,
        # understand fills these:
        "answer_shape": "", "multi_year": False, "multi_company": False,
        "tickers": [], "years": [], "unit_hint": "",
        "metric": "", "operation": "", "doc_type": "unknown",
        # retrieve fills:
        "table_ids": [], "shortlist": [],
        # generate_pandas fills:
        "evidence_tables": [], "frames": {}, "names": {},
        "solution": {}, "codegen_prompt": "",
        # execute_and_repair fills:
        "answer": 0.0, "pandas_query": "0.0", "evidence": [], "solver": "",
        "errors": [], "diag": {},
    }


_graph = None


def get_graph():
    """Default-config compiled graph, built once and cached."""
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph


async def arun_question(question_id: int, question: str) -> SolveState:
    return await get_graph().ainvoke(make_initial_state(question_id, question))


def run_question(question_id: int, question: str) -> SolveState:
    return run_sync(arun_question(question_id, question))


__all__ = [
    "SolveState", "arun_question", "build_graph", "get_graph",
    "make_initial_state", "make_solve_formula_facts", "make_solve_selection",
    "make_solve_raw_table_linker", "make_solve_raw_selection_linker",
    "make_solve_selection_facts",
    "make_solve_single_cell",
    "make_trace_capabilities", "make_verify_answer", "make_profile_validate",
    "run_question",
]
