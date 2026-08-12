"""FinanceAgent: the concrete agent driving the finance QA graph.

The class API is for configurable / experimental use (toggle reranker, thinking,
formula solver, etc. via FinanceAgentConfig):

    from finance_qa.agents.finance import FinanceAgent, FinanceAgentConfig
    agent = FinanceAgent(FinanceAgentConfig(codegen_max_tables=5))
    state = await agent.ainvoke(id=390, question="...")   # or agent.invoke(...) from sync code
    async for step in agent.astream(id=390, question="..."):
        ...

For the default-config functional entry point used by scripts, see
``finance_qa.agents.finance.graph.run_question``.
"""
from __future__ import annotations

from finance_qa.agents.base import BaseAgent
from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.graph import build_graph, make_initial_state
from finance_qa.agents.finance.state import FinanceState


class FinanceAgent(BaseAgent[FinanceState]):
    def __init__(self, config: FinanceAgentConfig | None = None) -> None:
        super().__init__(config or FinanceAgentConfig())

    def build_graph(self):
        return build_graph(self.config)

    def initial_state(self, *, id: int, question: str) -> FinanceState:
        return make_initial_state(id, question)
