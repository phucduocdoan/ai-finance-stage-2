"""The grounded-codegen pipeline: four nodes, one LLM call each.

Topology:
  understand → retrieve → generate_pandas → execute_and_repair → END

No router, no solver branches, no fallback chain. Every question takes the same
path, so a failure is attributable to a node rather than to which of six routes
it happened to take.

`understand` stays in front because retrieval hard-filters candidates on ticker /
year / doc_type and those come from it — the node that lifted DOCS_F2MACRO from
0.9248 to 0.9537. It is question understanding, not table understanding.

There is deliberately no evidence-selection step. It used to be its own node; it is
now a `[:codegen_max_tables]` slice of retrieval's ranking inside `generate_pandas`,
because that is all it ever was. Choosing which of those tables to read is part of
the call that writes the query — one decision by the one model that can see the
contents, instead of two decisions where the first was made blind.

What actually cost answers was not the slice but the schema: `target_row` /
`target_column` are singular, so the model answered every question with one cell,
including the 12 that compare two companies (0/12 correct). Letting the expression
span cells and dataframes took the "needs several cells" bucket from 0/13 to 5/13
and the whole gold set from 28/73 to 33/73, with queries reading more than one
dataframe going from 3/75 to 17/75. Widening the slice on top of that did *not*
help — see `codegen_max_tables`.

Loading does not touch `state["table_ids"]`, which is what gets submitted:
retrieval is scored on its own F2, so narrowing the submission would throw away
recall.

State is `FinanceState` plus two internal keys, so `scripts/build_submission.py`
and `submission_item()` consume this flow's records unchanged.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.state import FinanceState
from finance_qa.agents.finance.retrieve import make_retrieve_node
from finance_qa.agents.finance.understand import make_understand
from finance_qa.core.http import run_sync
from finance_qa.modules.data.service import ordered_table_names
from finance_qa.modules.data.table_store import load_frame, submission_csv_name
from finance_qa.modules.solve.codegen import PandasSolution, agenerate, build_prompt
from finance_qa.modules.solve.execute import aexecute
from finance_qa.modules.solve.verify import arevise, averify


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


def make_generate_pandas(config: FinanceAgentConfig):
    async def generate_pandas(state: SolveState) -> dict:
        names, frames, errors = load_evidence(
            list(state.get("table_ids") or []), config.codegen_max_tables
        )
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
        try:
            solution, prompt = await agenerate(
                state["question"], frames, names, thinking=config.codegen_thinking
            )
        except Exception as exc:  # noqa: BLE001 - reported, execute node handles the empty query
            # The prompt is handed on even though generation failed: the repair
            # call is the only remaining attempt, and a repair without the grids
            # answers `df1.iloc[0, 0]` — which is what the first measured run did
            # on all 26 questions whose codegen call was truncated.
            return {
                **loaded,
                "solution": PandasSolution().model_dump(),
                "codegen_prompt": build_prompt(state["question"], frames, names),
                "errors": errors + [f"codegen: {exc}"],
            }
        return {
            **loaded,
            "solution": solution.model_dump(),
            "codegen_prompt": prompt,
            "errors": errors,
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
            max_repairs=config.max_repairs,
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
    everything = [
        {"variable": var, "csv_path": f"data/{submission_csv_name(tid)}"}
        for var, tid in (state.get("names") or {}).items()
    ] or list(state.get("evidence") or [])
    used = [ev for ev in everything if ev["variable"] in result["pandas_query"]]
    return {
        "answer": float(result["answer"]),
        "pandas_query": result["pandas_query"],
        "evidence": used or list(state.get("evidence") or []),
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
        if not config.verify_answer or not frames or not prompt:
            return drop
        # A query that never ran has no cell to check, and the verifier shown one
        # reads the 0.0 as an answer and approves it (qid280). Repair already had
        # three attempts at this one; a fourth under a different prompt is not a
        # different idea.
        if (state.get("diag") or {}).get("units", {}).get("failed"):
            return drop
        try:
            verdict, _ = await averify(
                prompt, query, float(state.get("answer") or 0.0),
                frames, names, unit_hint=state.get("unit_hint") or "",
            )
        except Exception as exc:  # noqa: BLE001 - a failed check is not a failed answer
            return {**drop, "errors": list(state.get("errors") or []) + [f"verify: {exc}"]}
        if verdict.correct:
            return {**drop, "diag": {**(state.get("diag") or {}), "verify": {"correct": True}}}

        diag = {"verify": {"correct": False, "reason": verdict.reason, "before": query}}
        try:
            revised = await arevise(prompt, query, verdict.reason)
            result = await aexecute(
                revised, prompt, frames,
                question=state["question"], unit_hint=state.get("unit_hint") or "",
                names=names, max_repairs=config.max_repairs,
            )
        except Exception as exc:  # noqa: BLE001
            return {**drop, "errors": list(state.get("errors") or []) + [f"revise: {exc}"]}
        if result["diag"].get("failed"):
            return {**drop, "diag": {**(state.get("diag") or {}), **diag, "verify_kept": False}}
        return {**_emit(state, result, {**diag, "verify_kept": True}), **drop}

    return verify_answer


def build_graph(config: FinanceAgentConfig | None = None) -> StateGraph:
    config = config or FinanceAgentConfig()

    g = StateGraph(SolveState)
    g.add_node("understand", make_understand(config))
    g.add_node("retrieve", make_retrieve_node(config))
    g.add_node("generate_pandas", make_generate_pandas(config))
    g.add_node("execute_and_repair", make_execute_and_repair(config))
    g.add_node("verify_answer", make_verify_answer(config))

    g.set_entry_point("understand")
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve", "generate_pandas")
    g.add_edge("generate_pandas", "execute_and_repair")
    g.add_edge("execute_and_repair", "verify_answer")
    g.add_edge("verify_answer", END)
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
        "table_ids": [],
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
    "make_initial_state", "make_verify_answer", "run_question",
]
