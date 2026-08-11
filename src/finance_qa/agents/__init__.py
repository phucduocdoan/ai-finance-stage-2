"""Agent system: a reusable base + concrete domain agents.

``BaseAgent`` is the framework-level plumbing (lazy compile, invoke/stream);
domain agents live in subpackages (e.g. ``finance_qa.agents.finance``) and are
free to define their own state shape — the base is deliberately state-agnostic.
"""
from finance_qa.agents.base import BaseAgent

__all__ = ["BaseAgent", "FinanceAgent", "FinanceAgentConfig"]


def __getattr__(name: str):
    if name == "FinanceAgent":
        from finance_qa.agents.finance.agent import FinanceAgent

        return FinanceAgent
    if name == "FinanceAgentConfig":
        from finance_qa.agents.finance.config import FinanceAgentConfig

        return FinanceAgentConfig
    raise AttributeError(name)
