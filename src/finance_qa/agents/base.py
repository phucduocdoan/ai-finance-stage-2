"""Minimal base class for LangGraph-backed agents.

Captures only the plumbing that is genuinely common to any agent here: holding a
lazily-compiled graph and exposing invoke/stream/run over it. Topology and the
input→state mapping are agent-specific, so they stay abstract. There is
deliberately no ``build_node`` — nodes are unique functions with no generic
shape; a subclass registers them inside its own ``build_graph``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, Iterator, TypeVar

from langgraph.graph import StateGraph

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

    def invoke(self, **inputs: Any) -> StateT:
        return self.graph.invoke(self.initial_state(**inputs))

    def stream(self, **inputs: Any) -> Iterator[Any]:
        yield from self.graph.stream(self.initial_state(**inputs))

    run = invoke
