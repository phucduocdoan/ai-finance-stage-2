"""Configuration for the finance QA agent.

A leaf module (imports only the LLM default model) so both ``graph`` (the
topology builder + default-config ``run_question``) and ``agent`` (the
configurable class API) can import it without an import cycle.

Defaults reproduce the previously-hardcoded node behavior. Fields are grouped
into retrieval / solver production / codegen production / experiment-probe /
verification-package; the full history behind each default (measurements,
artifacts, doc references) lives in ``docs/config_flags.md``, keyed by field
name.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from finance_qa.core.llm import MODEL


def _flag(name: str, default: bool) -> bool:
    """Boolean default read from the environment, for A/B runs of one node."""
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", ""}


def _count(name: str, default: int) -> int:
    """Integer default read from the environment, for A/B runs of one node."""
    raw = os.environ.get(name)
    return default if raw is None or not raw.strip().isdigit() else int(raw)


@dataclass(frozen=True)
class FinanceAgentConfig:
    llm_model: str = MODEL

    # ── retrieval ──────────────────────────────────────────────────────────
    understand_thinking: bool = False    # understand node: enable_thinking
    reranker: str | None = "qwen3-0.6b"  # retrieve node: cross-encoder reranker
    judge_top_n: int = 20                # retrieve node: tables shown to the judge
    # retrieve node: dense index / text view. docs/config_flags.md#dense_backend
    dense_backend: str = "bge-m3"
    # retrieve node: judge enable_thinking. docs/config_flags.md#judge_thinking
    judge_thinking: bool = False
    frozen_fallback: bool = True         # retrieve node: use frozen cache on failure

    # ── solver production ─────────────────────────────────────────────────
    # Deterministic direct-cell arm for L1-shaped questions, falls back to codegen
    # on low confidence. docs/config_flags.md#cell_locator
    cell_locator: bool = field(default_factory=lambda: _flag("SOLVE_CELL_LOCATOR", True))
    # Deterministic non-selection formula solver over long_format facts.
    # docs/config_flags.md#formula_facts
    formula_facts: bool = field(default_factory=lambda: _flag("SOLVE_FORMULA_FACTS", True))
    # Thinking mode for the formula_facts plan emitter, off by default.
    formula_facts_planner_thinking: bool = field(
        default_factory=lambda: _flag("SOLVE_FORMULA_FACTS_PLANNER_THINKING", False)
    )
    # Raw-table linker for fixed-scope arithmetic outside long_format (note tables,
    # bank layouts, movement tables). docs/config_flags.md#raw_table_linker
    raw_table_linker: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER", True)
    )
    # LLM semantic linker over bounded candidates; Python still validates and builds
    # the expression. docs/config_flags.md#raw_table_linker_planner
    raw_table_linker_planner: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER_PLANNER", True)
    )
    # Thinking mode for the raw-table-linker planner, off by default.
    raw_table_linker_planner_thinking: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER_PLANNER_THINKING", False)
    )
    # Deterministic selection over the structured fact catalog, no LLM planner.
    # docs/config_flags.md#selection_facts
    selection_facts: bool = field(
        default_factory=lambda: _flag("SOLVE_SELECTION_FACTS", True)
    )
    # Raw-table selection (max/min) for note/detail metrics outside the structured
    # fact catalog. True for reproducibility, not measurement.
    # docs/config_flags.md#raw_selection_linker
    raw_selection_linker: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_SELECTION_LINKER", True)
    )

    # ── codegen production ────────────────────────────────────────────────
    # generate_pandas: tables shown to the model. More tables buy coverage and
    # lose accuracy. docs/config_flags.md#codegen_max_tables
    codegen_max_tables: int = 3
    # Table cap for questions naming a period (>=2 years).
    # docs/config_flags.md#codegen_max_tables_multi_year
    codegen_max_tables_multi_year: int = 5
    # Table cap for questions naming >=2 tickers, per (ticker, year) slot.
    # docs/config_flags.md#codegen_max_tables_multi_company
    codegen_max_tables_multi_company: int = field(
        default_factory=lambda: _count("SOLVE_MAX_TABLES_MULTI_COMPANY", 3)
    )
    # generate_pandas: enable_thinking. False — the local vLLM checkpoint returns
    # empty replies with thinking on. docs/config_flags.md#codegen_thinking
    codegen_thinking: bool = False
    max_repairs: int = 2                 # execute_and_repair: retries after an error

    # ── experiment / probe ────────────────────────────────────────────────
    # Structured fact solver (LLM plan + DuckDB/Python execution) over
    # long_format facts. docs/config_flags.md#structured_facts
    structured_facts: bool = field(
        default_factory=lambda: _flag("SOLVE_STRUCTURED_FACTS", False)
    )
    # Thinking mode for the structured_facts plan emitter.
    # docs/config_flags.md#structured_facts_planner_thinking
    structured_facts_planner_thinking: bool = field(
        default_factory=lambda: _flag("SOLVE_STRUCTURED_FACTS_PLANNER_THINKING", False)
    )
    # Experimental ratio-question candidate enrichment from recovered raw headers.
    # docs/config_flags.md#raw_table_linker_ratio_groups
    raw_table_linker_ratio_groups: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS", False)
    )
    # Deterministic formula/row-label hints in the codegen prompt. Measured: no
    # movement. docs/config_flags.md#codegen_metric_hints
    codegen_metric_hints: bool = field(
        default_factory=lambda: _flag("SOLVE_METRIC_HINTS", False)
    )
    # Deterministic table profiles beside each evidence grid (prompt context only).
    # docs/config_flags.md#codegen_table_profiles
    codegen_table_profiles: bool = field(
        default_factory=lambda: _flag("SOLVE_TABLE_PROFILES", False)
    )
    # Expand find_rows searches for derived metrics into primitive row labels.
    # docs/config_flags.md#codegen_metric_lookup
    codegen_metric_lookup: bool = field(
        default_factory=lambda: _flag("SOLVE_METRIC_LOOKUP", False)
    )
    # Lookup turns generate_pandas may spend before answering. 0 disables the loop.
    # Measured: did not work. docs/config_flags.md#codegen_tool_turns
    codegen_tool_turns: int = field(default_factory=lambda: _count("SOLVE_TOOL_TURNS", 0))
    # Show each table's rows (not just header) in the prompt. Ignored unless
    # codegen_tool_turns > 0. docs/config_flags.md#codegen_show_grids
    codegen_show_grids: bool = field(default_factory=lambda: _flag("SOLVE_SHOW_GRIDS", True))
    # Fan a selection question out over its axis, one sub-question per element.
    # Measured: mechanism runs, score does not move. docs/config_flags.md#selection_decompose
    selection_decompose: bool = field(default_factory=lambda: _flag("SOLVE_DECOMPOSE", False))
    # Tables shown per selection_decompose sub-question.
    # docs/config_flags.md#selection_sub_tables
    selection_sub_tables: int = field(default_factory=lambda: _count("SOLVE_SUB_TABLES", 6))
    # Show the repair call every query it has already tried, not just the last one.
    # docs/config_flags.md#repair_history
    repair_history: bool = field(default_factory=lambda: _flag("SOLVE_REPAIR_HISTORY", False))
    # Screening-shaped solution schema for "which companies satisfy X" questions.
    # Not yet measured against its pre-registered bar. docs/config_flags.md#screening_solver
    screening_solver: bool = field(default_factory=lambda: _flag("SOLVE_SCREENING", False))

    # ── verification / package ────────────────────────────────────────────
    # Post-solve diagnostic only, does not change answer/query/evidence.
    # docs/config_flags.md#profile_validate
    profile_validate: bool = field(
        default_factory=lambda: _flag("SOLVE_PROFILE_VALIDATE", False)
    )
    # execute_and_repair verification call; SOLVE_VERIFY_ANSWER=0 makes it a
    # pass-through. docs/config_flags.md#verify_answer
    verify_answer: bool = field(default_factory=lambda: _flag("SOLVE_VERIFY_ANSWER", True))
