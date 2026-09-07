"""Column/header enrichment for raw table linking.

The normalized DataFrame is still the execution authority. This module only
recovers structural text around columns so solvers can expose typed candidates
instead of asking an LLM to interpret ``Unnamed`` columns.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal, Sequence

import pandas as pd
from pydantic import BaseModel, Field

from finance_qa.modules.data.table_store import load_frame, source_csv
from finance_qa.modules.solve.common.columns import column_years, names_a_period
from finance_qa.modules.solve.common.context import meta_for, page_text
from finance_qa.modules.solve.common.lookup import label_column
from finance_qa.modules.solve.common.units import detect_column_unit, detect_table_unit
from finance_qa.modules.solve.solvers.table_profiles.link_schema import (
    RawCellRef,
    RawGroupCandidate,
    RawScopeSlot,
)
from finance_qa.modules.tools.numeric import NIL_MARKS, parse_number


ColumnSemanticRole = Literal[
    "lt_1y",
    "1_to_5y",
    "gt_5y",
    "total",
    "current",
    "prior",
    "overdue",
    "identifier",
]

_NON_WORD = re.compile(r"[^a-z0-9]+")
_UNNAMED = re.compile(r"^unnamed:\s*\d+$", re.I)
# `Mã số` 242 and `Thuyết minh` 16 are numeric, so a value candidate can be built
# from them unless the column is recognised as an identifier. OCR drops the space
# in these headers often enough (`Mãsố`, `Thuyếtminh`) that the patterns allow it.
_IDENTIFIER_COLUMN = re.compile(
    r"^(?:ma\s*so|mau\s*so|thuyet\s*minh|tm|stt|so\s*tt|ghi\s*chu|code|note)$"
)


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


def _is_nil(value: str) -> bool:
    return value.strip() == "" or value.strip() in NIL_MARKS


def _looks_like_subheader_row(raw: pd.DataFrame) -> bool:
    """Detect a second header row that pandas read as row 0.

    The common pattern is a first row of text subheaders followed by numeric
    data rows. A normal data table has row 0 with a row label plus numbers, so it
    should not match this predicate.
    """
    if raw.empty or raw.shape[1] < 3:
        return False
    values = [_text(value) for value in raw.iloc[0].tolist()]
    filled = [value for value in values if not _is_nil(value)]
    if len(filled) < 2:
        return False
    numeric = sum(1 for value in filled if parse_number(value) is not None)
    textish = len(filled) - numeric
    if numeric:
        return False
    if textish < max(2, int(len(filled) * 0.7)):
        return False

    sample = raw.iloc[1:min(len(raw), 6)]
    numeric_rows = 0
    for _, row in sample.iterrows():
        row_values = [_text(value) for value in row.tolist()]
        row_filled = [value for value in row_values if not _is_nil(value)]
        if not row_filled:
            continue
        row_numeric = sum(1 for value in row_filled if parse_number(value) is not None)
        if row_numeric >= 2:
            numeric_rows += 1
    return numeric_rows >= 1


def _clean_header_piece(value: object) -> str:
    text = _text(value)
    if not text or _UNNAMED.match(text):
        return ""
    return text


def _unique_pieces(values: Sequence[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_header_piece(value)
        norm = _norm(text)
        if not text or not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(text)
    return out


def _is_identifier_column(pieces: Sequence[str]) -> bool:
    return any(_IDENTIFIER_COLUMN.fullmatch(_norm(piece)) for piece in pieces)


def _semantic_roles(text: str) -> list[ColumnSemanticRole]:
    norm = _norm(text)
    roles: list[ColumnSemanticRole] = []
    if not norm:
        return roles

    if re.search(r"\b(?:tong\s+cong|tong|cong|total)\b", norm):
        roles.append("total")
    if re.search(r"\bqua\s+han\b", norm):
        roles.append("overdue")
    if re.search(r"\b(?:cuoi\s+nam|cuoi\s+ky|nam\s+nay|ky\s+nay|31\s+12|31/12)\b", norm):
        roles.append("current")
    if re.search(r"\b(?:dau\s+nam|dau\s+ky|nam\s+truoc|ky\s+truoc|01\s+01|01/01|1\s+1)\b", norm):
        roles.append("prior")

    lt_1y_patterns = (
        r"\bngan\s+han\b",
        r"\bduoi\s+(?:1|mot)\s+nam\b",
        r"\bduoi\s+12\s+thang\b",
        r"\bden\s+(?:1|mot)\s+nam\b",
        r"\bden\s+12\s+thang\b",
        r"\bden\s+(?:1|3|6|9)\s+thang\b",
        r"\btu\s+tren\s+(?:1|mot)\s+thang\s+den\s+3\s+thang\b",
        r"\btu\s+tren\s+3\s+thang\s+den\s+12\s+thang\b",
    )
    if any(re.search(pattern, norm) for pattern in lt_1y_patterns):
        roles.append("lt_1y")

    mid_patterns = (
        r"\btrung\s+han\b",
        r"\btu\s+(?:1|mot)\s+(?:toi|den)\s+5\s+nam\b",
        r"\btu\s+tren\s+(?:1|mot)\s+nam\s+den\s+5\s+nam\b",
        r"\b(?:1|mot)\s+(?:toi|den)\s+5\s+nam\b",
    )
    if any(re.search(pattern, norm) for pattern in mid_patterns):
        roles.append("1_to_5y")

    long_patterns = (
        r"\bdai\s+han\b",
        r"\btren\s+5\s+nam\b",
    )
    if any(re.search(pattern, norm) for pattern in long_patterns):
        roles.append("gt_5y")

    deduped: list[ColumnSemanticRole] = []
    for role in roles:
        if role not in deduped:
            deduped.append(role)
    return deduped


class LinkedColumnProfile(BaseModel):
    """One normalized DataFrame column enriched with raw header evidence."""

    index: int
    name: str
    raw_header_stack: list[str] = Field(default_factory=list)
    header_text: str = ""
    semantic_roles: list[ColumnSemanticRole] = Field(default_factory=list)
    unit: str = ""
    unit_from: str = ""
    is_identifier: bool = False
    resolved_year: int | None = None


def _raw_table(table_id: str) -> pd.DataFrame:
    return pd.read_csv(source_csv(table_id), dtype=str, keep_default_na=False)


def build_column_profiles(
    table_id: str,
    df: pd.DataFrame | None = None,
    raw: pd.DataFrame | None = None,
) -> list[LinkedColumnProfile]:
    """Build column profiles aligned to the normalized frame column positions."""
    if df is None:
        df = load_frame(table_id)
    if raw is None:
        raw = _raw_table(table_id)
    table_unit, table_unit_from = detect_table_unit(df, page_text(table_id))
    has_subheader = _looks_like_subheader_row(raw)
    try:
        row_label_col = label_column(df)
    except Exception:  # noqa: BLE001 - column enrichment can still use names
        row_label_col = None
    shifted_leaf_header = (
        has_subheader
        and row_label_col == str(df.columns[0])
        and len(raw.columns) == len(df.columns)
        and _UNNAMED.match(str(raw.columns[0])) is not None
        and bool(_clean_header_piece(raw.iloc[0, 0]))
    )

    # `Số cuối năm` / `Tại ngày 31 tháng 12 năm` headers lose the year at the OCR
    # line break; the report year in metadata is the only way back to it. Years
    # `column_years` inferred from column order alone are not carried here: on a
    # maturity-bucket table that guess would put a year on an unrelated column.
    years = {
        column: year
        for column, year in column_years(df, table_id, meta_for(table_id).get("year")).items()
        if names_a_period(column)
    }

    profiles: list[LinkedColumnProfile] = []
    for index, column in enumerate(df.columns):
        pieces: list[object] = [column]
        if index < len(raw.columns):
            pieces.append(raw.columns[index])
            if has_subheader and not raw.empty:
                subheader_index = index - 1 if shifted_leaf_header and index > 0 else index
                if not (shifted_leaf_header and index == 0) and 0 <= subheader_index < len(raw.columns):
                    pieces.append(raw.iloc[0, subheader_index])
        stack = _unique_pieces(pieces)
        header_text = " | ".join(stack)
        unit, unit_from = detect_column_unit(df, column)
        is_identifier = _is_identifier_column([str(column), *stack])
        roles = _semantic_roles(header_text)
        if is_identifier:
            roles.append("identifier")
        resolved = years.get(column)
        profiles.append(
            LinkedColumnProfile(
                index=index,
                name=str(column),
                raw_header_stack=stack,
                header_text=header_text,
                semantic_roles=roles,
                unit=unit or table_unit or "",
                unit_from=unit_from or table_unit_from or "",
                is_identifier=is_identifier,
                resolved_year=int(resolved) if str(resolved or "").isdigit() else None,
            )
        )
    return profiles


def build_column_group_candidates(
    table_id: str,
    slot: RawScopeSlot,
    *,
    df: pd.DataFrame | None = None,
    raw: pd.DataFrame | None = None,
    roles: Sequence[ColumnSemanticRole] = ("lt_1y", "total"),
    start_id: int = 1,
    max_rows: int = 80,
) -> list[RawGroupCandidate]:
    """Create row x semantic-column group candidates from real cells.

    This is a preprocessing primitive. It does not decide whether a group answers
    a question; a solver still has to present these groups to a planner and
    validate any selected ids.
    """
    if df is None:
        df = load_frame(table_id)
    if df.empty:
        return []
    profiles = build_column_profiles(table_id, df=df, raw=raw)
    columns_by_role: dict[ColumnSemanticRole, list[LinkedColumnProfile]] = {}
    for profile in profiles:
        if not profile.semantic_roles:
            continue
        for role in profile.semantic_roles:
            if role in roles:
                columns_by_role.setdefault(role, []).append(profile)
    if not columns_by_role:
        return []

    try:
        row_label_col = label_column(df)
    except Exception:  # noqa: BLE001 - no label column means no row-linked group
        return []
    meta = meta_for(table_id)
    context = " | ".join(
        str(meta.get(key))
        for key in ("section_title", "note_title", "header_flat")
        if meta.get(key)
    )
    out: list[RawGroupCandidate] = []
    for position, row in df.head(max_rows).iterrows():
        row_label = _text(row.get(row_label_col))
        if not row_label:
            continue
        for role in roles:
            role_columns = columns_by_role.get(role) or []
            cells: list[RawCellRef] = []
            for profile in role_columns:
                if profile.name == row_label_col or profile.is_identifier:
                    continue
                value = parse_number(str(row.get(profile.name)))
                if value is None:
                    continue
                cells.append(
                    RawCellRef(
                        table_id=table_id,
                        row_position=int(position),
                        column=profile.name,
                        value=float(value),
                        source_unit=(profile.unit or "unknown"),  # type: ignore[arg-type]
                        source_unit_from=profile.unit_from,
                    )
                )
            if not cells:
                continue
            out.append(
                RawGroupCandidate(
                    id=f"g{start_id + len(out)}",
                    slot_key=slot.key,
                    ticker=slot.ticker,
                    year=slot.year,
                    label=f"{row_label} :: {role}",
                    cells=cells,
                    semantic_role=role,
                    source_unit=(cells[0].source_unit or "unknown"),  # type: ignore[arg-type]
                    score=0.0,
                    table_context=context,
                )
            )
    return out


__all__ = [
    "ColumnSemanticRole",
    "LinkedColumnProfile",
    "build_column_group_candidates",
    "build_column_profiles",
]
