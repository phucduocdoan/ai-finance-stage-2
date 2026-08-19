"""Deterministic structural profile for one evidence table.

The raw CSV grid stays the source of truth for codegen. This profile is the
small, typed map around it: which columns look like row labels, which numeric
columns carry which year/unit, and which row labels match the main-statement
metric catalog. It is intentionally descriptive; answering still belongs to a
solver or to codegen.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.columns import column_years, money_columns
from finance_qa.modules.solve.common.context import meta_for, page_text
from finance_qa.modules.solve.common.units import detect_column_unit, detect_table_unit
from finance_qa.modules.solve.facts.structured_facts import metrics_in_text
from finance_qa.modules.tools.numeric import NIL_MARKS, parse_number


ColumnRole = Literal["label", "code", "numeric", "empty", "text"]

_NON_WORD = re.compile(r"[^a-z0-9]+")
_MA_SO = re.compile(r"\bm[aã]\s*s[oố]\b|thuy[eế]t\s+minh|code|stt", re.I)
_UNNAMED = re.compile(r"^unnamed:\s*\d+$", re.I)


def _norm(text: object) -> str:
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _numeric_ratio(series: pd.Series) -> float:
    raw = series.astype(str).str.strip()
    filled = raw[raw.ne("") & ~raw.isin(NIL_MARKS)]
    if filled.empty:
        return 0.0
    return float(filled.map(lambda value: parse_number(str(value))).notna().mean())


def _non_empty_count(series: pd.Series) -> int:
    raw = series.astype(str).str.strip()
    return int((raw.ne("") & ~raw.isin(NIL_MARKS)).sum())


def _role(series: pd.Series, column: str, numeric_columns: set[Any]) -> ColumnRole:
    if _non_empty_count(series) == 0:
        return "empty"

    norm_col = _norm(column)
    ratio = _numeric_ratio(series)
    if _MA_SO.search(str(column)) or norm_col in {"ma so", "stt"}:
        return "code"
    if column in numeric_columns or pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if ratio >= 0.8:
        return "code"

    samples = [_text(value) for value in series.head(12)]
    long_text = sum(1 for value in samples if len(_norm(value).split()) >= 2)
    if long_text >= 2 or ratio < 0.35:
        return "label"
    return "text"


def _profile_year(column: str, explicit_year: object, report_year: int | None) -> int | None:
    if str(explicit_year or "").isdigit():
        return int(explicit_year)
    if report_year is None:
        return None
    norm = _norm(column)
    if any(term in norm for term in ("nam nay", "cuoi nam", "cuoi ky", "31 12")):
        return report_year
    if any(term in norm for term in ("nam truoc", "dau nam", "dau ky", "01 01", "1 1")):
        return report_year - 1
    return None


def _row_label(row: pd.Series, label_columns: list[str]) -> str:
    for column in label_columns:
        text = _text(row.get(column))
        if text and parse_number(text) is None:
            return text
    text_cells = [
        _text(value)
        for value in row
        if _text(value) and parse_number(_text(value)) is None
    ]
    return " | ".join(text_cells[:2])


def _unique(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _norm(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


class ProfileColumn(BaseModel):
    """One column in the normalized frame."""

    index: int
    name: str
    role: ColumnRole
    year: int | None = None
    unit: str = ""
    unit_from: str = ""
    non_empty: int = 0
    numeric_ratio: float = 0.0


class ProfileRow(BaseModel):
    """One row label, indexed by the `.iloc` position codegen must use."""

    position: int
    label: str
    normalized_label: str
    metric_candidates: list[str] = Field(default_factory=list)


class TableProfile(BaseModel):
    """Typed table map handed to diagnostics or prompt renderers."""

    table_id: str
    ticker: str = ""
    year: int | None = None
    doc_type: str = ""
    statement_type: str = ""
    note_title: str = ""
    declared_unit: str = ""
    declared_unit_from: str = ""
    label_columns: list[str] = Field(default_factory=list)
    columns: list[ProfileColumn] = Field(default_factory=list)
    rows: list[ProfileRow] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)


def build_table_profile(table_id: str, df: pd.DataFrame | None = None) -> TableProfile:
    """Build a deterministic structural profile for ``table_id``."""
    if df is None:
        df = load_frame(table_id)
    meta = meta_for(table_id)
    page = page_text(table_id)
    table_unit, table_unit_from = detect_table_unit(df, page)
    years = column_years(df, table_id, meta.get("year"))
    numeric_columns = set(money_columns(df))
    report_year = int(meta["year"]) if str(meta.get("year") or "").isdigit() else None

    columns: list[ProfileColumn] = []
    for index, column in enumerate(df.columns):
        series = df.iloc[:, index]
        unit, unit_from = detect_column_unit(df, column)
        role = _role(series, column, numeric_columns)
        columns.append(
            ProfileColumn(
                index=index,
                name=str(column),
                role=role,
                year=_profile_year(str(column), years.get(column), report_year) if role == "numeric" else None,
                unit=(unit or table_unit or "") if role == "numeric" else "",
                unit_from=(unit_from or table_unit_from or "") if role == "numeric" else "",
                non_empty=_non_empty_count(series),
                numeric_ratio=round(_numeric_ratio(series), 3),
            )
        )

    label_columns = [column.name for column in columns if column.role == "label"]
    if not label_columns:
        label_columns = [column.name for column in columns if column.role == "text"][:1]

    rows: list[ProfileRow] = []
    for position, (_, row) in enumerate(df.iterrows()):
        label = _row_label(row, label_columns)
        if not label:
            continue
        rows.append(
            ProfileRow(
                position=position,
                label=label,
                normalized_label=_norm(label),
                metric_candidates=_unique(metrics_in_text(label)),
            )
        )

    flags = quality_flags(df, table_id, columns, label_columns)
    return TableProfile(
        table_id=table_id,
        ticker=str(meta.get("ticker") or ""),
        year=report_year,
        doc_type=str(meta.get("doc_type") or ""),
        statement_type=str(meta.get("statement_type") or ""),
        note_title=str(meta.get("note_title") or ""),
        declared_unit=table_unit or "",
        declared_unit_from=table_unit_from or "",
        label_columns=label_columns,
        columns=columns,
        rows=rows,
        quality_flags=flags,
    )


def quality_flags(
    df: pd.DataFrame,
    table_id: str,
    columns: list[ProfileColumn],
    label_columns: list[str],
) -> list[str]:
    """Cheap quality signals; useful for audit and routing, not scoring."""
    meta = meta_for(table_id)
    flags: list[str] = []
    if not any(column.role == "code" and _norm(column.name) == "ma so" for column in columns):
        flags.append("no_ma_so_column")
    if not label_columns:
        flags.append("no_label_column")
    if not any(column.role == "numeric" for column in columns):
        flags.append("no_numeric_columns")
    if any(_UNNAMED.match(column.name) for column in columns):
        flags.append("has_unnamed_columns")
    if any(column.year is None and column.role == "numeric" for column in columns):
        flags.append("yearless_numeric_columns")
    if len(df) > 60:
        flags.append("long_table")
    if len(df.columns) > 12:
        flags.append("wide_table")
    if str(meta.get("statement_type") or "") == "note" or meta.get("note_title"):
        flags.append("note_table")
    if str(meta.get("industry_segment") or "") == "bank":
        flags.append("bank_layout")
    return flags


def render_table_profile(profile: TableProfile, *, max_rows: int = 24) -> str:
    """Compact prompt block: structure only, not a replacement for the grid."""
    lines = [
        "Bản đồ bảng:",
        "  cột nhãn: " + (", ".join(profile.label_columns) or "?"),
        "  cờ chất lượng: " + (", ".join(profile.quality_flags) or "none"),
    ]
    if profile.declared_unit:
        lines.append(f"  đơn vị suy luận: {profile.declared_unit} ({profile.declared_unit_from})")

    lines.append("  cột:")
    for column in profile.columns:
        attrs = [column.role]
        if column.year:
            attrs.append(f"năm {column.year}")
        if column.unit:
            attrs.append(column.unit)
        lines.append(f"    [{column.index}] {column.name}: {', '.join(attrs)}")

    rows = profile.rows
    if len(rows) > max_rows:
        head = rows[: max_rows // 2]
        tail = rows[-(max_rows - len(head)) :]
        rows = [*head, *tail]
        hidden = len(profile.rows) - len(rows)
    else:
        hidden = 0
    lines.append("  hàng có nhãn:")
    last_position = -1
    for row in rows:
        if hidden and last_position >= 0 and row.position - last_position > 1:
            lines.append(f"    ... {hidden} hàng ở giữa ...")
            hidden = 0
        metric = f" | metric={','.join(row.metric_candidates)}" if row.metric_candidates else ""
        lines.append(f"    r{row.position}: {row.label}{metric}")
        last_position = row.position
    return "\n".join(lines)


def table_profile_context(table_id: str, df: pd.DataFrame | None = None, *, max_rows: int = 24) -> str:
    """Build and render a profile in one call."""
    return render_table_profile(build_table_profile(table_id, df), max_rows=max_rows)


__all__ = [
    "ProfileColumn",
    "ProfileRow",
    "TableProfile",
    "build_table_profile",
    "quality_flags",
    "render_table_profile",
    "table_profile_context",
]
