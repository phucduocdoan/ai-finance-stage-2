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


def _filled(series: pd.Series) -> pd.Series:
    raw = series.astype(str).str.strip()
    return raw[raw.ne("") & ~raw.isin(NIL_MARKS)]


def _parse_ratio(series: pd.Series) -> float:
    filled = _filled(series)
    if filled.empty:
        return 0.0
    return float(filled.map(parse_number).notna().mean())


def _empty_ratio(series: pd.Series) -> float:
    raw = series.astype(str).str.strip()
    if raw.empty:
        return 1.0
    return float((raw.eq("") | raw.isin(NIL_MARKS)).mean())


def _long_text_ratio(series: pd.Series) -> float:
    filled = _filled(series)
    if filled.empty:
        return 0.0
    words = filled.str.replace(r"[^A-Za-zÀ-ỹ0-9]+", " ", regex=True).str.split().str.len()
    return float((words >= 3).mean())


def repair_shifted_bank_header(df: pd.DataFrame) -> pd.DataFrame:
    """Repair common bank statement headers shifted one cell left."""
    cols = [str(col) for col in df.columns]
    if len(cols) < 4:
        return df
    if _looks_like_stt_label_shift(df, cols):
        out = df.iloc[:, :-1].copy()
        out.columns = cols[1:]
        return out
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


def _looks_like_stt_label_shift(df: pd.DataFrame, cols: list[str]) -> bool:
    """Rows lost their STT cell, so labels sit under `STT` and values shift left."""
    if len(cols) < 5:
        return False
    first = cols[0].strip().casefold()
    second = cols[1].strip().casefold()
    third = cols[2].strip().casefold()
    if first != "stt" or "chỉ tiêu" not in second or "thuyết minh" not in third:
        return False
    return (
        _long_text_ratio(df.iloc[:, 0]) >= 0.5
        and _long_text_ratio(df.iloc[:, 1]) < 0.25
        and _parse_ratio(df.iloc[:, 2]) >= 0.5
        and _parse_ratio(df.iloc[:, 3]) >= 0.5
        and _empty_ratio(df.iloc[:, -1]) >= 0.8
    )


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
