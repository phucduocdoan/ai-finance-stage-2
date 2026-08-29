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


def _with_columns(frame: pd.DataFrame, names: list[str], *, reset_index: bool = False) -> pd.DataFrame:
    """Copy `frame`, rename its columns to `names`, and return it.

    `reset_index=True` for a `body = df.iloc[1:]` slice, so the dropped
    header row's positions don't leak into what a later `.iloc` prints.
    """
    out = frame.reset_index(drop=True).copy() if reset_index else frame.copy()
    out.columns = names
    return out


def repair_shifted_bank_header(df: pd.DataFrame) -> pd.DataFrame:
    """Repair common bank statement headers shifted one cell left."""
    cols = [str(col) for col in df.columns]
    if len(cols) < 4:
        return df
    if _looks_like_stt_label_shift(df, cols):
        return _with_columns(df.iloc[:, :-1], cols[1:])
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

    return _with_columns(df, ["STT", "Chỉ tiêu", *cols[1:-1]])


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
    return _with_columns(body, repaired, reset_index=True)

def repair_group_leaf_header(df: pd.DataFrame) -> pd.DataFrame:
    """Name the trailing columns from a leaf header row when only the last group spans.

    ``repair_shifted_multilevel_header`` requires every named column to be a group with
    at least one leaf, which is the symmetric layout. The common asymmetric one is
    ``STT | Chỉ tiêu | Thuyết minh | Tại ngày`` where only `Tại ngày` spans two periods:
    its leaves (`31.12.2018Triệu VND`, `31.12.2017Triệu VND`) sit flush left in row 0,
    so the period columns come out ``Unnamed: n`` and a query for `Tại ngày` silently
    reads whichever period happened to land there. 144 of the 1,365 tables the v13 run
    actually queried are shaped that way, and on the labelled set the questions citing
    them score 33% against 49% for the rest.

    The leaves fill the rightmost ``len(leaves)`` columns, and each takes the nearest
    name at or left of its own position as a group prefix, so the symmetric layout comes
    out the same way the older function builds it. This runs only after that function
    declined, so tables it already handles are untouched.
    """
    if df.empty or len(df.columns) < 3:
        return df
    cols = [str(col) for col in df.columns]
    leaves = _shifted_leaves(df)
    if leaves is None or not 1 <= len(leaves) < len(cols):
        return df
    start = len(cols) - len(leaves)
    body = df.iloc[1:]
    # Only worth doing when a data-carrying column has no name, and every such column
    # has to fall inside the span the leaves cover; otherwise the shortfall is
    # something else and renaming would just relabel the wrong columns.
    unnamed_data = [
        i
        for i, col in enumerate(cols)
        if i > 0 and col.startswith("Unnamed:") and not _filled(body.iloc[:, i]).empty
    ]
    if not unnamed_data or min(unnamed_data) < start:
        return df
    # Exactly one group, so a leaf can take the name at its own position. Two or more
    # named columns inside the span means the groups have widths, and positions no
    # longer say which leaf belongs to which group: in
    # `ACB_financial_statements_2019_separate|97` the row-0 labels are `Quá hạn`,
    # `Trong hạn` and the unit annotation `Đơn vị: Triệu VND`, while `Quá hạn` really
    # spans the first two of eight maturity buckets. That layout is what the boundary
    # search in `repair_shifted_multilevel_header` is for; leave it there.
    if sum(1 for col in cols[start:] if not col.startswith("Unnamed:")) != 1:
        return df

    repaired = list(cols[:start])
    for offset, leaf in enumerate(leaves):
        i = start + offset
        group = next(
            (cols[j] for j in range(i, -1, -1) if not cols[j].startswith("Unnamed:")), ""
        )
        repaired.append(f"{group} | {leaf}" if group else leaf)
    if len({name.casefold() for name in repaired}) != len(repaired):
        return df
    return _with_columns(body, repaired, reset_index=True)


# Names a label column can carry. Used to find the one column whose content decides
# whether the whole frame is shifted: it is the only column whose expected content
# (long free text) is unmistakable from its name.
_LABEL_NAMES = ("chỉ tiêu", "khoản mục", "nội dung", "diễn giải", "danh mục", "tài sản")


def repair_right_shifted_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Shift every column name one place right when the header lost its stub cell.

    ``DTK_financial_statements_2024_consolidated|9`` has the header
    ``CHỈ TIÊU,Mã số,Thuyết minh,Số năm nay,Số năm trước,`` -- five names and a trailing
    empty -- over rows carrying six values, the first of which is an unheaded ordinal.
    Every name therefore sits one column left of its data: `Số năm nay` holds the note
    reference `VI.1` and the figure asked for is under `Số năm trước`. q214 fails on
    exactly that, with ``could not convert string to float: 'VI.1'`` in its errors.

    ``repair_shifted_bank_header`` covers this only when column 0 is `Unnamed:` or the
    header opens with the literal `STT | Chỉ tiêu | Thuyết minh` triple, and neither
    holds here because the label name landed in column 0.

    The evidence for the shift is the label column: a column named `Chỉ tiêu` that holds
    no free text while the column to its right does can only be misaligned. Combined
    with a single trailing unnamed column that carries data, the correction is forced.
    """
    cols = [str(col) for col in df.columns]
    if df.empty or len(cols) < 4:
        return df
    if not cols[-1].startswith("Unnamed:") or _filled(df.iloc[:, -1]).empty:
        return df
    if any(col.startswith("Unnamed:") for col in cols[:-1]):
        return df  # more than one name missing: not a one-cell shift
    shifted = any(
        any(key in col.casefold() for key in _LABEL_NAMES)
        and _long_text_ratio(df.iloc[:, i]) < 0.25
        and _long_text_ratio(df.iloc[:, i + 1]) >= 0.5
        for i, col in enumerate(cols[:-1])
    )
    if not shifted:
        return df
    return _with_columns(df, ["STT", *cols[:-1]])


__all__ = [
    "normalize_frame",
    "repair_group_leaf_header",
    "repair_right_shifted_columns",
    "repair_shifted_bank_header",
    "repair_shifted_multilevel_header",
]
