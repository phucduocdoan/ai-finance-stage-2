"""Finance QA agent: a self-contained LangGraph pipeline.

Public API:
    FinanceAgent, FinanceAgentConfig  — configurable class entry point
    run_question                      — default-config functional entry point
    build_graph                       — topology builder (uncompiled StateGraph)
"""

__all__ = ["FinanceAgent", "FinanceAgentConfig", "build_graph", "run_question"]


def __getattr__(name: str):
    if name == "FinanceAgent":
        from finance_qa.agents.finance.agent import FinanceAgent

        return FinanceAgent
    if name == "FinanceAgentConfig":
        from finance_qa.agents.finance.config import FinanceAgentConfig

        return FinanceAgentConfig
    if name in {"build_graph", "run_question"}:
        from finance_qa.agents.finance import graph

        return getattr(graph, name)
    raise AttributeError(name)
