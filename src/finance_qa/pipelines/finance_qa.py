"""Assemble the finance QA LangGraph topology.

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

Nodes that depend on config (understand/retrieve/formula) are built from
factories bound to a FinanceAgentConfig; the rest are plain node functions.
When config.enable_formula_solver is False the formula branch is omitted and
those operations route straight to repl.

`build_graph()` returns the *uncompiled* StateGraph (BaseAgent.graph compiles
it). `run_question()` keeps a default-config compiled singleton for the
functional entry point used by scripts.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.router import route_after_load, route_formula, route_lookup
from finance_qa.agents.finance.solvers.formula import make_formula_solver
from finance_qa.agents.finance.solvers.lookup import lookup_solver
from finance_qa.agents.finance.solvers.repl import repl_solver
from finance_qa.agents.finance.state import FinanceState
from finance_qa.agents.finance.understand import make_understand
from finance_qa.modules.data.service import load_node
from finance_qa.modules.rag.service import make_retrieve_node


def build_graph(config: FinanceAgentConfig | None = None) -> StateGraph:
    config = config or FinanceAgentConfig()
    formula_on = config.enable_formula_solver

    def _route(state: FinanceState) -> str:
        return route_after_load(state, formula_on=formula_on)

    g = StateGraph(FinanceState)

    g.add_node("understand", make_understand(config))
    g.add_node("retrieve",   make_retrieve_node(config))
    g.add_node("load",       load_node)
    g.add_node("lookup",     lookup_solver)
    g.add_node("repl",       repl_solver)
    if formula_on:
        g.add_node("formula", make_formula_solver(config))

    g.set_entry_point("understand")
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve",   "load")

    load_targets = {"lookup": "lookup", "repl": "repl"}
    if formula_on:
        load_targets["formula"] = "formula"
    g.add_conditional_edges("load", _route, load_targets)

    g.add_conditional_edges("lookup", route_lookup, {"repl": "repl", END: END})
    if formula_on:
        g.add_conditional_edges("formula", route_formula, {"repl": "repl", END: END})
    g.add_edge("repl", END)

    return g


def make_initial_state(question_id: int, question: str) -> FinanceState:
    """The empty state a run starts from (shared by run_question and FinanceAgent)."""
    return {
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


_graph = None


def get_graph():
    """Default-config compiled graph, built once and cached."""
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph


def run_question(question_id: int, question: str) -> FinanceState:
    """Run a single question through the default-config graph and return final state."""
    return get_graph().invoke(make_initial_state(question_id, question))
