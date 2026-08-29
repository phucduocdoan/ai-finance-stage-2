"""Markdown table rendering shared by the preprocessing stats builders."""
from __future__ import annotations

from collections import Counter


def markdown_counter_table(
    columns: tuple[str, str] | tuple[str, str, str],
    counter: Counter,
    *,
    total: int | None = None,
) -> list[str]:
    """Render `counter.most_common()` as markdown table lines (header, separator, rows).

    Pass a 2-column header for a plain count table, or 3 columns with `total`
    set to add a percentage-of-total column.
    """
    header = list(columns)
    align = ["---"] + ["---:"] * (len(header) - 1)
    lines = [f"| {' | '.join(header)} |", f"|{'|'.join(align)}|"]
    for key, count in counter.most_common():
        cells = [f"`{key}`", f"{count:,}"]
        if total is not None:
            cells.append(f"{100.0 * count / total:.1f}%" if total else "0%")
        lines.append(f"| {' | '.join(cells)} |")
    return lines
