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

State is `FinanceState` plus two internal keys, so `scripts/pipeline/build_submission.py`
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
from finance_qa.modules.solve.codegen.verify import arevise, averify
from finance_qa.modules.solve.pipeline.router import (
    SOLVER_CHAIN,
    make_solver_router,
    route_after_selection,
    selection_route,
)
from finance_qa.modules.solve.pipeline.evidence import codegen_budget, load_evidence
from finance_qa.modules.solve.pipeline.nodes.generate import (
    make_execute_and_repair,
    make_generate_pandas,
)
from finance_qa.modules.solve.pipeline.nodes import verify as verify_nodes
from finance_qa.modules.solve.pipeline.nodes.solvers import (
    make_solve_formula_facts,
    make_solve_raw_selection_linker,
    make_solve_raw_table_linker,
    make_solve_selection,
    make_solve_selection_facts,
    make_solve_single_cell,
    make_solve_structured_facts,
    make_trace_capabilities,
)


class SolveState(FinanceState, total=False):
    """`FinanceState` plus what the solve nodes hand each other.

    `codegen_prompt` is carried so the repair call can re-show the same grids
    instead of guessing, and both keys are dropped from the record written by the
    runner (the prompt is a few thousand chars per question).
    """

    evidence_tables: list[str]   # the tables codegen was shown
    codegen_prompt: str
    solution: dict[str, Any]


VERIFY_NARROW_SOLVERS_OBSERVE_ONLY = verify_nodes.VERIFY_NARROW_SOLVERS_OBSERVE_ONLY


def make_verify_answer(config: FinanceAgentConfig):
    """Compatibility wrapper for the moved verifier node factory."""
    return verify_nodes.make_verify_answer(
        config,
        verify_func=averify,
        revise_func=arevise,
        observe_narrow=VERIFY_NARROW_SOLVERS_OBSERVE_ONLY,
    )


def make_profile_validate(config: FinanceAgentConfig):
    """Compatibility wrapper for the moved profile-diagnostic node factory."""
    return verify_nodes.make_profile_validate(config)


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
    for after in [None, *(node for _, node, _ in SOLVER_CHAIN)]:
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
    "SOLVER_CHAIN", "SolveState", "VERIFY_NARROW_SOLVERS_OBSERVE_ONLY",
    "arun_question", "build_graph", "codegen_budget", "get_graph",
    "load_evidence", "make_execute_and_repair", "make_generate_pandas",
    "make_initial_state", "make_profile_validate", "make_solver_router",
    "make_solve_formula_facts", "make_solve_raw_selection_linker",
    "make_solve_raw_table_linker", "make_solve_selection",
    "make_solve_selection_facts", "make_solve_single_cell",
    "make_solve_structured_facts", "make_trace_capabilities",
    "make_verify_answer", "route_after_selection", "run_question",
    "selection_route",
]
