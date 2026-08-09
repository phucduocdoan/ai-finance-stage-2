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
    table_ids: list[str]

    # ── load node ───────────────────────────────────────────────────────────
    frames: dict[str, Any]   # var_name → pd.DataFrame
    names: dict[str, str]    # var_name → table_id

    # ── solver output ───────────────────────────────────────────────────────
    answer: float
    pandas_query: str
    evidence: list[dict]
    solver: str              # "lookup" | "repl" | "formula" | "failed"

    # ── debug ───────────────────────────────────────────────────────────────
    errors: list[str]
