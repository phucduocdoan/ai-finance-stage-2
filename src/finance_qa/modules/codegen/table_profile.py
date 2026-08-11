"""Structural profile of a single table, derived deterministically from its DataFrame and metadata.

Single source of truth for format/structural knowledge: which columns are labels, refs,
or value cols; where aggregate rows are; and what kind of statement this table represents.
Replaces scattered heuristics in generator.py, repairs.py, and PLAN_PROMPT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# ---------------------------------------------------------------------------
# Master constant sets — import from here, do NOT redefine elsewhere
# ---------------------------------------------------------------------------

_REF_COL_NAMES: frozenset[str] = frozenset({
    "mã số", "thuyết minh", "thuyết minh số", "tm", "stt", "stt.", "no.", "số"
})

_AGG_LABELS: frozenset[str] = frozenset({
    "cộng", "tổng", "tổng cộng", "tổng số", "cộng tổng cộng"
})

_MAIN_STATEMENT_TYPES: frozenset[str] = frozenset({
    "balance_sheet", "income_statement", "cash_flow", "equity_change"
})

_CURRENT_COL_MARKERS = ("năm nay", "số cuối năm", "cuối năm", "cuối kỳ", "kỳ này")
_PRIOR_COL_MARKERS = ("năm trước", "số đầu năm", "đầu năm", "đầu kỳ", "kỳ trước")


# ---------------------------------------------------------------------------
# TableProfile
# ---------------------------------------------------------------------------

@dataclass
class TableProfile:
    label_col: str               # first non-numeric col (row labels, e.g. "Unnamed: 0")
    ref_cols: list[str]          # reference cols to ignore (Mã số, TM, STT, …)
    value_cols: list[str]        # numeric value cols (period data)
    agg_rows: list[int]          # row indices of aggregate rows (TỔNG CỘNG, Cộng, …)
    table_kind: str              # "main_report" | "note" | "unknown"
    year_map: dict[str, int] = field(default_factory=dict)  # col name → report year


def profile_table(df: pd.DataFrame, table_id: str, meta: dict) -> TableProfile:
    """Derive a TableProfile from a DataFrame and its metadata entry.

    `meta` must have keys: caption (str), period_cols (set[str]), statement_type (str).
    `table_id` has the form "{report_id}|{table_pos}", e.g. "VCB_..._2023|3".
    """
    is_numeric_col = lambda c: (
        pd.api.types.is_float_dtype(df[c]) or pd.api.types.is_integer_dtype(df[c])
    )

    # value_cols: all numeric-dtype cols that are not known reference cols.
    # period_cols metadata is intentionally ignored here — it is often incomplete
    # (e.g. lists only the current-year col, omitting the prior-year col) and would
    # cause the Cột giá trị annotation to silently hide valid value columns.
    ref_key_set = _REF_COL_NAMES
    value_cols = [
        c for c in df.columns
        if is_numeric_col(c) and str(c).strip().casefold() not in ref_key_set
    ]
    value_set = set(value_cols)

    # label_col: first non-numeric, non-value col
    non_numeric = [c for c in df.columns if c not in value_set and not is_numeric_col(c)]
    label_col = non_numeric[0] if non_numeric else (str(df.columns[0]) if len(df.columns) > 0 else "")

    # ref_cols: known reference column names (case-insensitive whitelist), excluding label_col
    col_lower_map: dict[str, str] = {}
    for c in df.columns:
        key = str(c).strip().casefold()
        if key not in col_lower_map:
            col_lower_map[key] = str(c)
    ref_cols = [
        col_lower_map[key]
        for key in _REF_COL_NAMES
        if key in col_lower_map and col_lower_map[key] != label_col
    ]

    # agg_rows: rows where label_col text exactly matches an aggregate label
    agg_rows: list[int] = []
    if label_col in df.columns:
        for i, val in enumerate(df[label_col]):
            if str(val).strip().casefold() in _AGG_LABELS:
                agg_rows.append(i)

    # table_kind: from statement_type metadata field
    stmt_type = (meta.get("statement_type") or "unknown").strip()
    if stmt_type == "note":
        table_kind = "note"
    elif stmt_type in _MAIN_STATEMENT_TYPES:
        table_kind = "main_report"
    else:
        table_kind = "unknown"

    # year_map: map column names to report years using standard Vietnamese column name conventions
    year_map: dict[str, int] = {}
    report_match = re.search(r"financial_statements_(20\d{2})", table_id)
    if report_match:
        report_year = int(report_match.group(1))
        for col in df.columns:
            folded = str(col).casefold()
            if any(m in folded for m in _CURRENT_COL_MARKERS):
                year_map[str(col)] = report_year
            elif any(m in folded for m in _PRIOR_COL_MARKERS):
                year_map[str(col)] = report_year - 1

    return TableProfile(
        label_col=label_col,
        ref_cols=ref_cols,
        value_cols=value_cols,
        agg_rows=agg_rows,
        table_kind=table_kind,
        year_map=year_map,
    )
