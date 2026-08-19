"""Render a table as prompt context: metadata header + the actual grid.

The old codegen prompt showed the model a *schema* — column names, dtypes, row
count, and a truncated list of unique labels — and never the cell values. That is
the wrong abstraction for these tables: the row a question asks for is
identified by Vietnamese label text, the period is identified by a column
header, and the unit is often declared in a data cell. A schema hides all three.

Showing the whole grid is affordable here, which is the fact that makes this
simple. Measured over the corpus: a table CSV is 767 chars at p50, 1673 at p90,
3023 at max, and 100% are under 6000. Truncation is a fallback, not the norm.
"""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from finance_qa.core.paths import TABLE_METADATA_PATH
from finance_qa.modules.solve.common.columns import year_legend
from finance_qa.modules.solve.common.units import detect_table_unit

# Only the fields a solver can act on. The full record has 26 keys, most of them
# retrieval-side scores and provenance flags that would just spend prompt budget.
_META_FIELDS = (
    "company_name", "ticker", "year", "doc_type", "page_number",
    "statement_type", "section_title", "note_id", "note_title", "header_flat",
    "num_rows", "num_cols", "first_col_labels",
    # ~350 chars of the page around the table. Carried for one reason: it holds
    # the "Đơn vị tính: Triệu đồng" line for tables whose banner row was lost in
    # extraction, which is the only unit signal 3 of the 12 undeclared gold
    # tables have.
    "context_page_text",
)

# Above this many rows the grid is shown as head+tail. Chosen so the p90 table
# (which is well under it) is never truncated.
_MAX_GRID_ROWS = 60
_HEAD_ROWS, _TAIL_ROWS = 40, 15

# Row-label budget per candidate line. Metadata stores at most 20 labels, joined
# to 168 chars at p50 and 599 at p90, so most candidates print in full.
_MAX_LABEL_CHARS = 400
_HEAD_LABELS, _TAIL_LABELS = 6, 6


@lru_cache(maxsize=1)
def table_metadata() -> dict[str, dict]:
    """All table metadata keyed by ``"{report_id}|{table_pos}"``.

    Read once per process (146k rows, ~4 s). A missing file is not fatal: the
    grid alone is enough to generate a query, so this degrades to an empty map
    rather than taking the run down.
    """
    out: dict[str, dict] = {}
    if not TABLE_METADATA_PATH.exists():
        return out
    with TABLE_METADATA_PATH.open(encoding="utf-8") as fh:
        for line in filter(str.strip, fh):
            record = json.loads(line)
            key = f"{record['report_id']}|{record['table_pos']}"
            out[key] = {field: record.get(field) for field in _META_FIELDS}
    return out


def meta_for(table_id: str) -> dict:
    return table_metadata().get(table_id, {})


def page_text(table_id: str) -> str:
    """Text of the page the table sits on, where "Đơn vị tính: ..." is declared."""
    return meta_for(table_id).get("context_page_text") or ""


def _grid(df: pd.DataFrame) -> str:
    """The frame as text, with the integer positions the query will index by.

    ``to_string`` keeps the RangeIndex in the left margin, which is exactly what
    ``df.iloc[i]`` needs — so the model reads the row number it must write.
    """
    if len(df) <= _MAX_GRID_ROWS:
        return df.to_string(max_colwidth=70)
    head = df.head(_HEAD_ROWS).to_string(max_colwidth=70)
    tail = df.tail(_TAIL_ROWS).to_string(max_colwidth=70, header=False)
    hidden = len(df) - _HEAD_ROWS - _TAIL_ROWS
    return f"{head}\n   ... {hidden} hàng ở giữa bị ẩn ...\n{tail}"


def table_context(variable: str, table_id: str, df: pd.DataFrame, *, grid: bool = True) -> str:
    """Full context block for one evidence table.

    `grid=False` keeps the header — identity, declared unit, column names and the
    year legend — and drops the rows. That is the shape a lookup-first prompt
    wants: the period/unit facts a query needs are all in the header, while the
    rows are what a second near-duplicate table turns into noise.
    """
    meta = meta_for(table_id)
    unit, where = detect_table_unit(df, meta.get("context_page_text") or "")

    header = [f"### {variable} = {table_id}"]
    company = meta.get("company_name") or meta.get("ticker") or ""
    if company:
        header.append(f"Doanh nghiệp: {company} ({meta.get('ticker') or '?'})")
    header.append(
        f"Báo cáo: năm {meta.get('year') or '?'}, {meta.get('doc_type') or '?'}, "
        f"trang {meta.get('page_number') or '?'}"
    )
    header.append(f"Loại bảng: {meta.get('statement_type') or 'unknown'}")
    for label, key in (("Mục", "section_title"), ("Thuyết minh", "note_title")):
        if meta.get(key):
            header.append(f"{label}: {meta[key]}")
    header.append(f"Kích thước: {df.shape[0]} hàng x {df.shape[1]} cột")
    header.append(
        f"Đơn vị bảng khai báo: {unit} (tại {where})" if unit
        else "Đơn vị bảng khai báo: không tìm thấy"
    )
    # 56% of the tables shown name no year in any money column, so the model has
    # to join "Số cuối năm" to the report year and does not — see solve.columns.
    legend = year_legend(df, table_id, meta.get("year"))
    if legend:
        header.append(legend)
    if not grid:
        header.append("Cột: " + " | ".join(str(c) for c in df.columns))
        return "\n".join(header)
    return "\n".join(header) + "\n\n" + _grid(df)


def _label_preview(labels: list) -> str:
    """Row labels for a candidate line, keeping both ends when it must truncate.

    Head-only truncation cost the first smoke test its answer: q45 asks for
    "TỔNG NỢ PHẢI TRẢ", which is label 13 of 20 on the balance sheet, so cutting
    at 8 hid the one row that distinguished the right table from a note about
    "các khoản phải trả khác". Totals sit at the *bottom* of a statement, and
    aggregate questions target totals, so the tail is the half worth keeping.
    """
    text = "; ".join(str(x) for x in labels)
    if len(text) <= _MAX_LABEL_CHARS:
        return text
    head = "; ".join(str(x) for x in labels[:_HEAD_LABELS])
    tail = "; ".join(str(x) for x in labels[-_TAIL_LABELS:])
    return f"{head} … {tail}"


def candidate_line(index: int, table_id: str) -> str:
    """One-line summary of a retrieval candidate, for evidence selection.

    Selection runs over up to ~200 candidates, so this stays metadata-only: the
    grid is what the *chosen* tables get, and paying for it here is what made the
    old prompt spend its 12,000-char budget on 18 tables at ~800 chars each.
    """
    meta = meta_for(table_id)
    preview = _label_preview(meta.get("first_col_labels") or [])
    parts = [
        f"[{index}] {table_id}",
        f"{meta.get('ticker') or '?'} {meta.get('year') or '?'} {meta.get('doc_type') or '?'}",
        meta.get("statement_type") or "unknown",
    ]
    for key in ("section_title", "note_title"):
        if meta.get(key):
            parts.append(str(meta[key]))
    if meta.get("header_flat"):
        parts.append(f"cột: {meta['header_flat']}")
    if preview:
        parts.append(f"hàng: {preview}")
    return " | ".join(parts)


__all__ = ["candidate_line", "meta_for", "page_text", "table_context", "table_metadata"]
