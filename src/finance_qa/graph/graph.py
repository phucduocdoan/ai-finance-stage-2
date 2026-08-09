"""Assemble the finance QA LangGraph.

Topology:
  understand → retrieve → load → _route ──► lookup → _route_lookup ──► END
                                        │                           └──► repl → END
                                        ├──► formula → _route_formula ──► END
                                        │                             └──► repl → END
                                        └──► repl → END

Router logic:
  operation=lookup + single_cell → lookup → if planner error → repl
  operation=formula|compare|multi_step → formula → if formula_skip → repl
  else → repl
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from finance_qa.graph.nodes.understand import understand
from finance_qa.graph.nodes.load import load
from finance_qa.graph.nodes.retrieve_targeted import retrieve_targeted
from finance_qa.graph.nodes.solvers.formula import formula_solver
from finance_qa.graph.nodes.solvers.lookup import lookup_solver
from finance_qa.graph.nodes.solvers.repl import repl_solver
from finance_qa.graph.state import FinanceState


def _route(state: FinanceState) -> str:
    op = state.get("operation", "")
    if op == "lookup" and state.get("answer_shape") == "single_cell":
        return "lookup"
    if op in ("formula", "compare", "multi_step"):
        return "formula"
    return "repl"


def _route_formula(state: FinanceState) -> str:
    return "repl" if state.get("solver") == "formula_skip" else END


def _route_lookup(state: FinanceState) -> str:
    # lookup_solver sets solver="lookup_failed" when the planner errored.
    # Checking solver (not the shared errors list) avoids false positives from
    # retrieve_targeted warnings that appear even when lookup succeeds.
    return "repl" if state.get("solver") == "lookup_failed" else END


def build_graph():
    g = StateGraph(FinanceState)

    g.add_node("understand",        understand)
    g.add_node("retrieve_targeted", retrieve_targeted)
    g.add_node("load",              load)
    g.add_node("lookup",            lookup_solver)
    g.add_node("formula",           formula_solver)
    g.add_node("repl",              repl_solver)

    g.set_entry_point("understand")
    g.add_edge("understand",        "retrieve_targeted")
    g.add_edge("retrieve_targeted", "load")
    g.add_conditional_edges("load",    _route,         {"lookup": "lookup", "formula": "formula", "repl": "repl"})
    g.add_conditional_edges("lookup",  _route_lookup,  {"repl": "repl", END: END})
    g.add_conditional_edges("formula", _route_formula, {"repl": "repl", END: END})
    g.add_edge("repl",   END)

    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_question(question_id: int, question: str) -> FinanceState:
    """Run a single question through the graph and return final state."""
    initial: FinanceState = {
        "id": question_id,
        "question": question,
        # understand fills these:
        "answer_shape": "", "multi_year": False, "multi_company": False,
        "tickers": [], "years": [], "unit_hint": "",
        "metric": "", "operation": "", "doc_type": "unknown",
        # retrieve fills:
        "table_ids": [],
        # load fills:
        "frames": {}, "names": {},
        # solver fills:
        "answer": 0.0, "pandas_query": "0.0", "evidence": [], "solver": "",
        "errors": [],
    }
    return get_graph().invoke(initial)
