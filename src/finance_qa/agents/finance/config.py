"""Configuration for the finance QA agent.

A leaf module (imports only the LLM default model) so both ``graph`` (the
topology builder + default-config ``run_question``) and ``agent`` (the
configurable class API) can import it without an import cycle.

Defaults reproduce the previously-hardcoded node behavior.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from finance_qa.core.llm import MODEL


def _flag(name: str, default: bool) -> bool:
    """Boolean default read from the environment, for A/B runs of one node."""
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", ""}


@dataclass(frozen=True)
class FinanceAgentConfig:
    llm_model: str = MODEL
    understand_thinking: bool = False    # understand node: enable_thinking
    reranker: str | None = "qwen3-0.6b"  # retrieve node: cross-encoder reranker
    judge_top_n: int = 20                # retrieve node: tables shown to the judge
    # The judge's own docstring recommends thinking (recall@15 69.3% vs 84-89%), but
    # that was measured with no reranker over the whole pool, where the judge had to
    # re-sort a noisy list itself. With qwen3-0.6b reranking and judge_top_n=20 the
    # input is already ordered: measured on the 59 gold questions that name their
    # table, thinking=False here beats the base run's thinking=True at every K
    # (MRR 0.714 vs 0.611, top-3 81.4% vs 71.2%) and costs ~15x less latency.
    judge_thinking: bool = False         # retrieve node: judge enable_thinking
    frozen_fallback: bool = True         # retrieve node: use frozen cache on failure

    # solve_qa pipeline (grounded codegen). Retrieval hands the solver 14 tables at
    # the median and 79 at worst, so codegen reads the head of that list.
    #
    # 3, and measured: more tables buy coverage and lose accuracy. Over the 73 gold
    # questions, raising this from 3 to 10 does put every needed table in front of
    # the model more often (37 -> 47 questions hold the full gold set) and grows the
    # prompt from 7.4k to 22.2k chars (p50) — but the share of those questions the
    # model then gets wrong rises from 38% to 53%, and the total falls 33 -> 29. The
    # extra grids are mostly near-duplicates of the right one (same company, same
    # year, different note), and the failures they cause are literal: a column name
    # taken from df2 used to index df5. Coverage is not the binding constraint;
    # telling one table from nine like it is, is.
    codegen_max_tables: int = 3          # generate_pandas: tables shown to the model
    # False, and measured: the vLLM server on 8990 now serves Qwen/Qwen3.5-9B under
    # the old alias, and with enable_thinking=True it returns an empty reply at every
    # budget tried (2048/4096/8192 completion tokens, finish_reason=length, both
    # `content` and `reasoning_content` empty) — the qwen3 reasoning parser never sees
    # the block close. thinking=False answers the same prompt in 66 tokens.
    codegen_thinking: bool = False       # generate_pandas: enable_thinking
    max_repairs: int = 2                 # execute_and_repair: retries after an error
    # The check costs one call on every question plus two on the ones it rejects,
    # so it is a flag: `SOLVE_VERIFY_ANSWER=0` turns the node into a pass-through
    # and gives the A/B its control arm without a second code path.
    verify_answer: bool = field(default_factory=lambda: _flag("SOLVE_VERIFY_ANSWER", True))
