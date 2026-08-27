"""Evidence table loading and codegen budget selection."""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.utils import slot_round_robin, year_round_robin
from finance_qa.modules.data.service import ordered_table_names
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.screening import is_screening


def load_evidence(table_ids: list[str], max_tables: int) -> tuple[dict, dict, list[str]]:
    """Load the head `max_tables` tables of retrieval's ranking as df1, df2, ...

    Returns ``(names, frames, errors)``. Duplicate ids are collapsed because the
    judge's picks and the primary-statement tail overlap, and a table that will
    not load is dropped from the variables rather than shipped as evidence
    pointing at a frame no query can read.
    """
    errors: list[str] = []
    ordered = list(dict.fromkeys(table_ids))[:max_tables]
    names = ordered_table_names(ordered)
    frames: dict[str, Any] = {}
    for var, table_id in names.items():
        try:
            frames[var] = load_frame(table_id)
        except Exception as exc:  # noqa: BLE001 - reported, run continues
            errors.append(f"load: {table_id} -> {exc}")
    return {var: tid for var, tid in names.items() if var in frames}, frames, errors


def codegen_budget(
    state: Mapping[str, Any], config: FinanceAgentConfig
) -> tuple[list[str], int]:
    """`(table_ids in load order, how many to load)` for one question.

    A question that names several companies or several years is the only kind
    that can run out of slots before it runs out of relevance, so it is the only
    kind that gets more of them — and it needs its ids interleaved, because
    ranking alone puts the third company's table at position 14.

    Companies are checked first: a question naming both several companies and
    several years (85 of the 310 multi-ticker questions) needs a table per
    (ticker, year) pair, which is what `slot_round_robin` spreads and what the
    multi-company budget is sized for. `year_round_robin` would interleave only
    the years and leave the companies to the ranking.
    """
    table_ids = list(state.get("table_ids") or [])
    tickers = list(state.get("tickers") or [])
    years = list(state.get("years") or [])
    if len(tickers) >= 2:
        needed = len(tickers) * max(len(years), 1)
        cap = config.codegen_max_tables_multi_company
        # `config.py` (codegen_max_tables_multi_company) measured this widening
        # alone as flat: coverage went 310/310 and score stayed 4/38, because a
        # single pandas expression has nowhere to put a filter. That is what
        # `screening_solver` (screening.py) adds, so once it is on this pairs the
        # wider budget with something for the extra companies to be filtered by.
        if config.screening_solver and is_screening(str(state.get("question") or "")):
            cap = 12
        return (
            slot_round_robin(table_ids),
            max(config.codegen_max_tables, min(needed, cap)),
        )
    if state.get("multi_year"):
        return year_round_robin(table_ids), config.codegen_max_tables_multi_year
    return table_ids, config.codegen_max_tables


__all__ = ["codegen_budget", "load_evidence"]
