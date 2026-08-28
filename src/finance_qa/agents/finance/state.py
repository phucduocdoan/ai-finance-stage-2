"""Shared state flowing through the finance QA graph."""
from __future__ import annotations

from typing import Any, TypedDict


class FinanceState(TypedDict):
    # ── input ──────────────────────────────────────────────────────────────
    id: int
    question: str

    # ── understand node fills these ─────────────────────────────────────────
    answer_shape: str    # "single_cell" | "derived"
    multi_year: bool
    multi_company: bool
    tickers: list[str]
    years: list[int]
    unit_hint: str
    metric: str          # chỉ tiêu chính: gross_margin | de_ratio | revenue | ...
    operation: str       # lookup | formula | compare | multi_step
    doc_type: str        # consolidated | separate | unknown

    # ── retrieve node ───────────────────────────────────────────────────────
    table_ids: list[str]     # the submitted list, judge picks + primary tail
    shortlist: list[str]     # everything past the hard filter, searchable by find_rows

    # ── loaded evidence ──────────────────────────────────────────────────────
    frames: dict[str, Any]   # var_name → pd.DataFrame
    names: dict[str, str]    # var_name → table_id

    # ── solver output ───────────────────────────────────────────────────────
    answer: float
    pandas_query: str
    evidence: list[dict]
    solver: str              # which solver answered, e.g. "cell_locator" | "raw_table_linker" | "codegen"

    # ── debug ───────────────────────────────────────────────────────────────
    errors: list[str]
    diag: dict[str, Any]     # solver internals, for offline failure taxonomy
