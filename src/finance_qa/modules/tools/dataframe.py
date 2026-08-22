"""DataFrame normalization and repair helpers."""
from __future__ import annotations

import re
from bisect import bisect_right

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


def _shifted_leaves(df: pd.DataFrame) -> list[str] | None:
    """Leaf labels of a second header row that landed in the data as row 0.

    The extractor drops that row's leading label cell, so the leaves sit flush left
    with the trailing columns empty. Anything numeric means it is a real data row.
    """
    first = [str(value).strip() for value in df.iloc[0]]
    leaves = [value for value in first if value]
    if len(leaves) < 2:
        return None
    if first[: len(leaves)] != leaves or any(first[len(leaves) :]):
        return None
    if any(parse_number(value) is not None for value in leaves):
        return None
    return leaves


def _named_run(cols: list[str]) -> tuple[int, int] | None:
    """Span of real header labels, which `Unnamed:` columns pad on both sides."""
    named = [i for i, col in enumerate(cols) if col.strip() and not col.startswith("Unnamed:")]
    if not named or named != list(range(named[0], named[-1] + 1)):
        return None
    return named[0], named[-1]


def repair_shifted_multilevel_header(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild a two-row header whose second row landed in the data.

    Row 0 holds group labels for a few spans, row 1 holds the leaves of every span,
    and the leaves are one column left of where they belong. Every column that holds
    real numbers then comes out named `Unnamed: n`, so reading the table by column
    name returns another period's figure: in `KLB_2019_consolidated|67` the column
    called `Số đầu năm` holds the *closing* fair value, and the opening one has no
    name at all. See `docs/multiyear_failures_2026-08-22.md` §5.

    The old version hard-coded a `số cuối` / `số đầu` pair and then filed every leaf
    under the first group, so the symmetric layout, by far the most common one, came
    out with both halves labelled `số cuối` and duplicate column names.

    Group boundaries come from the leaf row repeating its first label once per group:
    `Phải nộp, Phải thu | Phải nộp, Đã nộp, Giảm khác | Phải nộp, Phải thu` is three
    groups of unequal width, and `SJG_2018_consolidated|45` really is shaped that way.
    Every named column has to end up a group with at least one leaf, the leaves have to
    cover every column that carries data, and no two rebuilt names may collide. Anything
    else leaves the frame alone: a named column left without a leaf was the old bug's
    signature, and it means the layout is something this function cannot read.
    """
    if df.empty or len(df.columns) < 5:
        return df
    cols = [str(col) for col in df.columns]
    leaves = _shifted_leaves(df)
    run = _named_run(cols)
    if leaves is None or run is None:
        return df

    start, groups = run[0], cols[run[0] : run[1] + 1]
    boundaries = [i for i, leaf in enumerate(leaves) if leaf == leaves[0]]
    if len(boundaries) != len(groups) or start < 1 or start + len(leaves) > len(cols):
        return df
    body = df.iloc[1:]
    if any(not _filled(body.iloc[:, i]).empty for i in range(start + len(leaves), len(cols))):
        return df

    repaired = [
        *cols[:start],
        *(
            f"{groups[bisect_right(boundaries, i) - 1]} | {leaf}"
            for i, leaf in enumerate(leaves)
        ),
        *cols[start + len(leaves) :],
    ]
    if len({name.casefold() for name in repaired}) != len(repaired):
        return df
    out = body.reset_index(drop=True).copy()
    out.columns = repaired
    return out

__all__ = [
    "normalize_frame",
    "repair_shifted_bank_header",
    "repair_shifted_multilevel_header",
]
