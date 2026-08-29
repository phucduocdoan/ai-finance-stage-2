"""Offline test for the page-prose indexing in `metadata_enrichment`.

`table_pos` is 1-based, so table N's page is `offsets[N-1]`. The builder used
`offsets[N]` and gave 59.5% of all 146,246 rows the *next* table's page, which is
where `detect_unit` looks for "Đơn vị tính".

    PYTHONPATH=src .venv_bge/bin/python tests/test_metadata_enrichment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.data.preprocessing.offline.metadata_enrichment import (  # noqa: E402
    find_table_offsets,
    page_prose_for,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


# Three pages, one table each, each page declaring a different unit.
OCR = """===== PAGE 1 =====
Đơn vị: triệu đồng
<table><tr><td>a</td></tr></table>
===== PAGE 2 =====
Đơn vị: nghìn đồng
<table><tr><td>b</td></tr></table>
===== PAGE 3 =====
Đơn vị: VND
<table><tr><td>c</td></tr></table>
"""

offsets = find_table_offsets(OCR)
check("three tables found", len(offsets) == 3)

check("table 1 reads page 1", "triệu đồng" in page_prose_for(OCR, offsets, 1))
check("table 2 reads page 2", "nghìn đồng" in page_prose_for(OCR, offsets, 2))
# The regression: table 3 is the last one, so the old `offsets[table_pos]` ran off
# the end and returned "" for the final table of every one of the 1,944 reports.
check("table 3 reads page 3", "VND" in page_prose_for(OCR, offsets, 3))
check("the last table is not blank", page_prose_for(OCR, offsets, 3) != "")

check("a table_pos past the end is empty", page_prose_for(OCR, offsets, 4) == "")
check("table_pos 0 is not a valid 1-based position", page_prose_for(OCR, offsets, 0) == "")
check("no OCR text -> empty", page_prose_for("", offsets, 1) == "")

# Two tables on one page share its prose; that is the 40.5% the off-by-one hid in.
SAME_PAGE = """===== PAGE 1 =====
Đơn vị: triệu đồng
<table><tr><td>a</td></tr></table>
<table><tr><td>b</td></tr></table>
"""
same = find_table_offsets(SAME_PAGE)
check(
    "tables sharing a page share its prose",
    page_prose_for(SAME_PAGE, same, 1) == page_prose_for(SAME_PAGE, same, 2) != "",
)

print("tất cả PASS")
