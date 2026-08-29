"""Tier-aware header flattening + unit extraction, built on top of `grid.py`.

`enrich_csv`'s `header_flat` (`metadata_enrichment.py`) only ever reads CSV row 0, because
the CSVs themselves come from a naive BeautifulSoup `<td>` walk (`extract_tables.py`) that
never expands `rowspan`/`colspan`. Two failure modes follow directly from that:

1. A real multi-row header (period group on row 0, sub-period on row 1) collapses to row 0
   alone, dropping the second tier.
2. Column boundaries drift wherever a `colspan`/`rowspan` cell exists, so a "unit" cell
   (`VND`, `Triệu đồng`, `Đơn vị tính: VND`) lands inside the *text* of a neighboring header
   cell instead of its own slot -- `docs/retrieval_preprocessing_2026-08-21.md` §3.1 catalogs
   this as `2023VND`, `Số cuối nămTriệu đồng`, `Số cuối năm | Đơn vị tính: VND`, etc.

This module re-derives the header from the properly expanded `Grid` (see `grid.py`), which
fixes (2) structurally, and adds real tier detection for (1): it walks down from row 0 while
rows still look like header rows (not numeric data, not a uniform section-title row), merges
each column's tier values into one path, and pulls out any unit token it finds along the way
into a separate `unit` field instead of leaving it fused into the header text.

Only extracts a unit when it recognizes the scale/currency wording (VND/VNĐ/USD, optionally
prefixed by `triệu`/`nghìn`/`tỷ`, or an explicit `Đơn vị tính`/`ĐVT` label). Bare `đồng` is
never extracted outside that explicit label -- same reasoning as the repo-refactor's
`corpus/units.py`: it is a common syllable in unrelated words (`hoạt động`, `hội đồng`),
so blind stripping would eat real header text on many tables it never touches on the
corpus's actual unit declarations, which almost always spell out the full word or an
explicit label.
"""

from __future__ import annotations

import re
from collections import Counter

from finance_qa.modules.data.preprocessing.offline.grid import Grid

# A cell that "looks like a number": digits with thousands separators, optional leading
# minus or parens for negative, optional trailing percent. Financial-statement OCR also
# uses a bare dash for "no value" -- treated as data-like too, not as a header label.
_NUMERIC_CELL_RE = re.compile(r"^[\(\-]?[\d][\d.,]*[\)%]?$")
_DASH_CELL_RE = re.compile(r"^[\-–]{1,3}$")

# Section-title rows repeat the exact same string in every column, courtesy of a colspan
# that now spans the whole grid width post-expansion (`LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH
# DOANH`, `Ngắn hạn`). That is body content one row into the table's data area, not a
# second header tier, so it stops tier detection rather than extending it.
_LABEL_RE = re.compile(r"đơn\s*vị\s*t[íi]nh|đvt\s*[:\-]", re.IGNORECASE)

_SCALE = r"(?:triệu|nghìn|tỷ)"
_CURRENCY_BARE = r"(?:vnđ|vnd|usd)"
# No leading/trailing `\b`: the whole point is to catch OCR that glued the unit onto the
# text next to it (`2023VND`, `VNDNăm trước`, `Số cuối nămTriệu đồng`). `đồng` bare is
# deliberately absent from this pattern -- see module docstring.
_UNIT_RE = re.compile(rf"{_SCALE}\s*đồng|{_SCALE}\s*{_CURRENCY_BARE}|{_CURRENCY_BARE}", re.IGNORECASE)

_SCALE_MAP = {"triệu": "Triệu", "nghìn": "Nghìn", "tỷ": "Tỷ"}


def _is_numericish(cell: str) -> bool:
    c = cell.strip()
    if not c:
        return False
    return bool(_NUMERIC_CELL_RE.match(c) or _DASH_CELL_RE.match(c))


def _row_is_data(row: list[str]) -> bool:
    """A row belongs to the table body once at most one of its filled cells is
    non-numeric (that one being the row label) and at least one cell is a real number."""
    non_empty = [c.strip() for c in row if c.strip()]
    if not non_empty:
        return False
    numericish = sum(1 for c in non_empty if _is_numericish(c))
    return numericish >= 1 and (len(non_empty) - numericish) <= 1


def _row_is_uniform(row: list[str]) -> bool:
    non_empty = [c.strip() for c in row if c.strip()]
    return len(non_empty) >= 2 and len(set(non_empty)) == 1


def header_tier_rows(cells: list[list[str]], *, max_tiers: int = 4, max_scan: int = 8) -> list[list[str]]:
    """The grid rows that make up the header, top-down.

    Stops the first time a row looks like body data or a uniform section-title row.
    Blank spacer rows are skipped without counting toward either the tier cap or the scan
    window. Always keeps at least row 0 if nothing else qualifies (`enrich_csv`'s prior
    behavior was "row 0, whatever it contains" -- this only ever adds tiers on top of that,
    never removes the fallback).

    `max_tiers=4` matches this corpus's observed header depth (1/2/3/4 tiers at
    71.5/25.7/2.3/0.6%, measured in the repo-refactor project on the same corpus).
    """
    tiers: list[list[str]] = []
    for row in cells[:max_scan]:
        if not any(c.strip() for c in row):
            continue
        if tiers and _row_is_uniform(row):
            break
        if _row_is_data(row):
            break
        tiers.append(row)
        if len(tiers) >= max_tiers:
            break
    if not tiers and cells:
        tiers = [cells[0]]
    return tiers


def _canonical_unit(matched: str) -> str:
    low = matched.lower()
    scale = next((v for k, v in _SCALE_MAP.items() if k in low), None)
    currency = "USD" if "usd" in low else "VND"
    return f"{scale} {currency}" if scale else currency


def extract_unit(text: str) -> tuple[str, str | None]:
    """Split one header cell into (remaining label text, unit found or None).

    A cell that itself IS a unit declaration (`Đơn vị tính: VND`, `ĐVT: Triệu đồng`) is
    dropped entirely -- it carries no column-label information -- even when no currency
    word inside it is one we recognize (still boilerplate, just an unrecognized wording of
    it). A cell that merely *contains* a unit token keeps everything else.
    """
    if _LABEL_RE.search(text):
        m = _UNIT_RE.search(text)
        if m:
            return "", _canonical_unit(m.group(0))
        if re.search(r"đồng", text, re.IGNORECASE):
            return "", "VND"
        return "", None

    m = _UNIT_RE.search(text)
    if not m:
        return text, None
    remainder = (text[: m.start()] + text[m.end() :]).strip()
    return remainder, _canonical_unit(m.group(0))


def merge_columns(tiers: list[list[str]]) -> tuple[list[str], list[str]]:
    """Per-column tier path (unit stripped) + every unit token found along the way."""
    n_cols = max((len(r) for r in tiers), default=0)
    col_paths: list[str] = []
    units_found: list[str] = []
    for c in range(n_cols):
        # Collapse consecutive duplicates: a rowspan cell repeats the same text into every
        # grid row it covers, so two tiers showing the same value are one label, not two.
        seen: list[str] = []
        for row in tiers:
            if c >= len(row):
                continue
            cell = row[c].strip()
            if cell and (not seen or seen[-1] != cell):
                seen.append(cell)

        pieces: list[str] = []
        for cell in seen:
            remainder, unit = extract_unit(cell)
            if unit:
                units_found.append(unit)
            remainder = remainder.strip(" -:")
            if remainder:
                pieces.append(remainder)
        col_paths.append(" - ".join(pieces))
    return col_paths, units_found


def flatten_header(grid: Grid) -> tuple[str, str]:
    """(header_flat, unit) for one table, from its expanded grid."""
    tiers = header_tier_rows(grid.cells)
    col_paths, units = merge_columns(tiers)
    header_flat = " | ".join(p for p in col_paths if p)
    unit = Counter(units).most_common(1)[0][0] if units else ""
    return header_flat, unit
