"""DataFrame normalization and repair helpers."""
from __future__ import annotations

import re

import pandas as pd

from finance_qa.modules.tools.numeric import NIL_MARKS, parse_number


def normalize_frame(df: pd.DataFrame, min_ratio: float = 0.6) -> pd.DataFrame:
    """Convert mostly numeric columns to floats and leave label columns untouched."""
    out = df.copy()
    for col in out.columns:
        raw = out[col].astype(str).str.strip()
        is_nil = raw.isin(NIL_MARKS)
        filled = raw[raw.ne("") & ~is_nil]
        if filled.empty:
            continue
        if filled.map(parse_number).notna().mean() >= min_ratio:
            out[col] = raw.map(lambda v: 0.0 if v in NIL_MARKS else parse_number(v))
    return out


def repair_shifted_bank_header(df: pd.DataFrame) -> pd.DataFrame:
    """Repair common bank statement headers shifted one cell left."""
    cols = [str(col) for col in df.columns]
    if len(cols) < 4:
        return df
    shifted = (
        cols[0].startswith("Unnamed:")
        and cols[1].strip().casefold() == "thuyết minh"
        and cols[-1].startswith("Unnamed:")
    )
    if not shifted:
        return df

    second = df.iloc[:, 1].astype(str).str.strip()
    filled = second[second.ne("")]
    if filled.empty or filled.map(parse_number).isna().mean() < 0.8:
        return df

    out = df.copy()
    out.columns = ["STT", "Chỉ tiêu", *cols[1:-1]]
    return out


def repair_shifted_multilevel_header(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct a legacy-extracted two-row header with a spanned group."""
    if df.empty or len(df.columns) < 5:
        return df
    cols = [str(col) for col in df.columns]
    first = [str(value).strip() for value in df.iloc[0]]
    subheaders = [value for value in first if value]
    if len(subheaders) < 2:
        return df
    if first[: len(subheaders)] != subheaders or any(first[len(subheaders) :]):
        return df
    if any(parse_number(value) is not None for value in subheaders):
        return df

    group_start = len(cols) - len(subheaders) - 1
    if group_start < 1 or group_start + 1 >= len(cols):
        return df
    group_name = cols[group_start]
    final_name = cols[group_start + 1]
    if not (
        "số cuối" in group_name.casefold()
        and "số đầu" in final_name.casefold()
        and all(col.startswith("Unnamed:") for col in cols[group_start + 2 :])
    ):
        return df

    leaf_columns = [*cols[:group_start], *subheaders, final_name]
    if len({column.casefold() for column in leaf_columns}) == len(leaf_columns):
        repaired_columns = leaf_columns
    else:
        repaired_columns = [
            *cols[:group_start],
            *(f"{group_name} | {subheader}" for subheader in subheaders),
            final_name,
        ]
    if len(repaired_columns) != len(cols):
        return df
    out = df.iloc[1:].reset_index(drop=True).copy()
    out.columns = repaired_columns
    return out

__all__ = [
    "normalize_frame",
    "repair_shifted_bank_header",
    "repair_shifted_multilevel_header",
]
