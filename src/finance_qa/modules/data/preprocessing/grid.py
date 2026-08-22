"""Expand a table's `rowspan`/`colspan` HTML markup into a rectangular grid.

Ported from `r2ai/corpus/grid.py` (sibling repo `ai-finance-stage-2-refactor`), where the
guards below were calibrated against this same ViFinQA OCR corpus (see that repo's
TICKETS-A.md §0.1/§0.2). Ported rather than imported so this repo does not depend on the
other one; the guards and their rationale are kept unchanged.

Not using lxml/bs4: the source repo measured this corpus's markup as clean enough not to
need a real parser (no nested `<table>`, no attributes on `<table>`/`<tr>`, `colspan`/
`rowspan` only ever appear on `<td>` as `="N"`).

Pure function: takes an HTML string, returns a grid + a list of warnings. No file IO, no
logging -- the caller decides what to do with `warnings`.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

_RE_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_RE_CELL = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
_RE_SPAN = re.compile(r'\b(rowspan|colspan)="(\d+)"')

# `<img src="data:image/jpeg;base64,...">` shows up embedded straight in OCR'd cells --
# it's a scanned image, not content. Left in place, one cell balloons to tens of
# thousands of base64 characters, bloating the parquet and adding BM25 noise. The
# base64 alphabet never contains `>`, so `[^>]*` is safe here.
_RE_IMG = re.compile(r"<img[^>]*>", re.S | re.I)

# A handful of cells carry rowspan > 20 (max observed 927). That isn't a real merged
# cell -- it's one cell "swallowing" hundreds of trailing empty `<tr></tr>` rows.
# Expanding it literally would duplicate one string into 927 grid rows. 20 is a safe
# threshold: the largest rowspan seen on a real merged cell in this corpus is 7.
_MAX_ROWSPAN = 20

# Cap runaway column counts. Only a few tables end up with >500 columns, and they are
# all headers that OCR blew apart cell-by-cell rather than real wide tables.
_MAX_COLS = 64

# Allocation guard: an anomalous `colspan` has to be capped *before* the grid is built,
# or we'd allocate hundreds of thousands of cells only to truncate down to 64 afterward.
_MAX_COLSPAN = 128


@dataclass(frozen=True)
class Grid:
    """A rectangular grid. Invariant: every row has exactly `n_cols` elements (asserted
    at construction time)."""

    cells: list[list[str]]
    warnings: tuple[str, ...] = ()
    # The MOST `<td>` cells seen on any single row, counted BEFORE colspan expansion.
    # Differs from `n_cols` for at least one table in the corpus where every row is a
    # single `<td colspan="2">` -- i.e. a one-column list rendered two columns wide,
    # where expanding to two identical columns would be a presentation artifact, not
    # data. Callers doing a "trivial table" check should use this field, not `n_cols`.
    n_cells_max: int = 0

    @property
    def n_rows(self) -> int:
        return len(self.cells)

    @property
    def n_cols(self) -> int:
        return len(self.cells[0]) if self.cells else 0


def _clean(body: str) -> str:
    return " ".join(_html.unescape(_RE_IMG.sub("", body)).split())


def _spans(attrs: str) -> tuple[int, int]:
    rowspan = colspan = 1
    for name, value in _RE_SPAN.findall(attrs):
        n = max(1, int(value))
        if name == "rowspan":
            rowspan = n
        else:
            colspan = n
    return rowspan, colspan


def expand_table(inner_html: str) -> Grid:
    """Expand a table the way a browser would. `inner_html` is the part BETWEEN
    `<table>...</table>`.

    Only pass the inside of the table: OCR junk tags (`<x>`, `<fcel>`, `<z>`) always sit
    OUTSIDE `<table>` in this corpus, so scanning at the whole-document level would pick
    up false matches.
    """
    warnings: list[str] = []
    rows: list[dict[int, str]] = []
    pending: dict[int, tuple[str, int]] = {}  # col -> (value, rows remaining)
    n_cells_max = 0

    for raw_row in _RE_ROW.findall(inner_html):
        row: dict[int, str] = {}
        # Drop still-active rowspan cells into their column before reading new `<td>`s.
        for col, (value, rows_left) in list(pending.items()):
            row[col] = value
            if rows_left <= 1:
                del pending[col]
            else:
                pending[col] = (value, rows_left - 1)

        col = 0
        raw_cells = _RE_CELL.findall(raw_row)
        n_cells_max = max(n_cells_max, len(raw_cells))
        for attrs, body in raw_cells:
            rowspan, colspan = _spans(attrs)
            if rowspan > _MAX_ROWSPAN:
                warnings.append(f"rowspan={rowspan} exceeds {_MAX_ROWSPAN}, dropped to 1")
                rowspan = 1
            if colspan > _MAX_COLSPAN:
                warnings.append(f"colspan={colspan} exceeds {_MAX_COLSPAN}, dropped to 1")
                colspan = 1

            text = _clean(body)
            for _ in range(colspan):
                while col in row:  # skip past a column already claimed by a rowspan
                    col += 1
                row[col] = text
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1

        rows.append(row)

    width = max((max(r) + 1 for r in rows if r), default=0)

    # Trim fully-empty trailing columns, e.g. one table with 1,954 columns where ~1,918
    # trailing cells are empty because its header got blown apart by OCR.
    while width > 0 and not any(r.get(width - 1) for r in rows):
        width -= 1

    if width > _MAX_COLS:
        warnings.append(f"{width} cols exceeds {_MAX_COLS}, truncated")
        width = _MAX_COLS

    # Re-align ragged rows. This step CREATES the rectangular invariant, not just checks it.
    if len({(max(r) + 1 if r else 0) for r in rows}) > 1:
        warnings.append("ragged row lengths, padded/truncated to a common width")

    cells = [[r.get(c, "") for c in range(width)] for r in rows]
    assert all(len(r) == width for r in cells), "grid not rectangular after alignment"

    return Grid(cells=cells, warnings=tuple(warnings), n_cells_max=n_cells_max)
