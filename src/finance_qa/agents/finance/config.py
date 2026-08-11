"""Configuration for the finance QA agent.

A leaf module (imports only the LLM default model) so both ``graph`` (the
topology builder + default-config ``run_question``) and ``agent`` (the
configurable class API) can import it without an import cycle.

Defaults reproduce the previously-hardcoded node behavior. ``formula_max_tokens``
is raised to 8192 (from the langchain default 2048) so thinking-mode reasoning
has room to reach the final answer instead of truncating mid-``<think>`` — this
matches the planner's thinking budget in the 0.2688 pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

from finance_qa.core.llm import MODEL


@dataclass(frozen=True)
class FinanceAgentConfig:
    llm_model: str = MODEL
    understand_thinking: bool = False    # understand node: enable_thinking
    formula_thinking: bool = True        # formula solver: reasoning-call thinking
    formula_max_tokens: int = 8192       # formula reasoning budget (thinking needs room; matches planner)
    reranker: str | None = "qwen3-0.6b"  # retrieve node: cross-encoder reranker
    judge_top_n: int = 20                # retrieve node: tables shown to the judge
    enable_formula_solver: bool = True   # False → formula/compare/multi_step route to repl
    frozen_fallback: bool = True         # retrieve node: use frozen cache on failure
