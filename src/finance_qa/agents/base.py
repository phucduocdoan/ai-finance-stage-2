"""Minimal base class for LangGraph-backed agents.

Captures only the plumbing that is genuinely common to any agent here: holding a
lazily-compiled graph and exposing ainvoke/invoke/astream over it. Topology and the
input→state mapping are agent-specific, so they stay abstract. There is
deliberately no ``build_node`` — nodes are unique functions with no generic
shape; a subclass registers them inside its own ``build_graph``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Generic, TypeVar

from langgraph.graph import StateGraph

from finance_qa.core.http import run_sync

StateT = TypeVar("StateT")


class BaseAgent(ABC, Generic[StateT]):
    def __init__(self, config: Any) -> None:
        self.config = config
        self._compiled: Any = None

    @abstractmethod
    def build_graph(self) -> StateGraph:
        """Return the (uncompiled) graph: topology + node registration."""

    @abstractmethod
    def initial_state(self, **inputs: Any) -> StateT:
        """Map call inputs into the graph's initial state."""

    @property
    def graph(self) -> Any:
        """Compiled graph, built once and cached."""
        if self._compiled is None:
            self._compiled = self.build_graph().compile()
        return self._compiled

    async def ainvoke(self, **inputs: Any) -> StateT:
        return await self.graph.ainvoke(self.initial_state(**inputs))

    def invoke(self, **inputs: Any) -> StateT:
        """Sync `ainvoke`.

        It goes through the async graph rather than ``graph.invoke`` because the
        finance nodes are coroutines, which the sync Pregel runner cannot drive.
        The reverse is safe: LangGraph runs sync nodes in a thread under
        ``ainvoke``, so a fully-sync subclass still works here.
        """
        return run_sync(self.ainvoke(**inputs))

    async def astream(self, **inputs: Any) -> AsyncIterator[Any]:
        async for step in self.graph.astream(self.initial_state(**inputs)):
            yield step
