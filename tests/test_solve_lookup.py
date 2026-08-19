"""Regression tests for `modules.solve.common.lookup` (row search over the shortlist).

Frames and metadata are stubbed: the point under test is the matching, the
filtering and the rendering, none of which should need 146k metadata rows or a
CSV on disk to be exercised.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.common import lookup


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


TOTAL_LABEL = "Tổng chi phí thuế TNDN hiện hành (của Ngân hàng và các công ty con)"

FRAMES = {
    "TCB_2024_consolidated|41": pd.DataFrame({
        "Chỉ tiêu": [
            "Chi phí thuế TNDN hiện hành của Ngân hàng(thuế suất: 20%)",
            TOTAL_LABEL,
            "Lợi nhuận sau thuế",
        ],
        "Năm nay": ["1.234", "1.500", "9.000"],
        "Năm trước": ["1.000", "1.200", "8.000"],
    }),
    "VCB_2023_consolidated|7": pd.DataFrame({
        "Chỉ tiêu": ["Chi phí thuế TNDN hiện hành", "Tiền gửi khách hàng"],
        "Số cuối năm": ["555", "777"],
    }),
    "TCB_2024_consolidated|99": pd.DataFrame(),
    "KBC_2020_consolidated|9": pd.DataFrame({
        "Chỉ tiêu": ["Tổng nợ phải trả", "Vốn chủ sở hữu", "Tổng tài sản"],
        "Số cuối năm": ["300", "200", "500"],
    }),
    "BAB_2020_separate|6": pd.DataFrame({
        "STT": ["I", "II"],
        "Chỉ tiêu": ["Tiền gửi của khách hàng", "TỔNG NỢ PHẢI TRẢ"],
        "Thuyết minh": ["17", ""],
        "31/12/2020": ["86564976", "108950874"],
    }),
}

META = {
    "TCB_2024_consolidated|41": {
        "ticker": "TCB", "year": 2024, "doc_type": "consolidated",
        "statement_type": "income_statement",
    },
    "VCB_2023_consolidated|7": {
        "ticker": "VCB", "year": 2023, "doc_type": "consolidated",
        "statement_type": "balance_sheet",
    },
    "TCB_2024_consolidated|99": {"ticker": "TCB", "year": 2024},
    "KBC_2020_consolidated|9": {
        "ticker": "KBC", "year": 2020, "doc_type": "consolidated",
        "statement_type": "balance_sheet",
    },
    "BAB_2020_separate|6": {
        "ticker": "BAB", "year": 2020, "doc_type": "separate",
        "statement_type": "balance_sheet",
    },
}

lookup.load_frame = lambda table_id: FRAMES[table_id]
lookup.meta_for = lambda table_id: META.get(table_id, {})
lookup.detect_table_unit = lambda df, page: ("triệu VND", "banner")

ALL = list(FRAMES)


# ── matching ────────────────────────────────────────────────────────────────
hits = lookup.search_rows(ALL, "chi phí thuế TNDN hiện hành")
labels = [h.label for h in hits]
check("an accented query matches", len(hits) >= 3)
check("the row label comes back untruncated", TOTAL_LABEL in labels)
check(
    "the component row and the total row both come back",
    "Chi phí thuế TNDN hiện hành của Ngân hàng(thuế suất: 20%)" in labels,
)
check(
    "an exact label outranks the same phrase inside a longer one",
    labels[0] == "Chi phí thuế TNDN hiện hành",
)

check(
    "an unaccented query matches the accented label",
    [h.label for h in lookup.search_rows(ALL, "chi phi thue tndn hien hanh")] == labels,
)
check(
    "punctuation and case are ignored",
    [h.label for h in lookup.search_rows(ALL, "CHI-PHÍ  THUẾ, TNDN hiện hành!")] == labels,
)
check("an empty query matches nothing", lookup.search_rows(ALL, "   ") == [])
check("a query for another metric does not drag in the tax rows",
      [h.label for h in lookup.search_rows(ALL, "lợi nhuận sau thuế")] == ["Lợi nhuận sau thuế"])
# A one-word query ("ROE", "Doanh thu") is legitimate, so it is allowed to match
# broadly; `limit` is what keeps the reply short.
check("a one-word query matches every row carrying that word",
      len(lookup.search_rows(ALL, "chi", limit=99)) == 3)
check("an empty frame is skipped, not raised on", all(h.table_id != "TCB_2024_consolidated|99" for h in hits))
check(
    "the label column may sit after an STT/code column",
    [h.label for h in lookup.search_rows(ALL, "Tổng nợ phải trả", ticker="BAB")]
    == ["TỔNG NỢ PHẢI TRẢ"],
)
check("metric expansion is opt-in",
      lookup.search_rows(ALL, "Tỷ số D/E") == [])
metric_hits = lookup.search_rows(ALL, "Tỷ số D/E", expand_metrics=True)
metric_labels = {h.label for h in metric_hits}
check("metric expansion finds liabilities", "Tổng nợ phải trả" in metric_labels)
check("metric expansion finds equity", "Vốn chủ sở hữu" in metric_labels)

hit = next(h for h in hits if h.label == TOTAL_LABEL)
check("the .iloc position is the row's position", hit.position == 1)
check("every value column is returned with its header", hit.values == {"Năm nay": "1.500", "Năm trước": "1.200"})
check("the table summary names ticker, year and unit",
      "TCB" in hit.table_summary and "2024" in hit.table_summary and "triệu VND" in hit.table_summary)


# ── filters ─────────────────────────────────────────────────────────────────
check(
    "the ticker filter excludes other companies",
    {h.table_id for h in lookup.search_rows(ALL, "chi phí thuế", ticker="VCB")} == {"VCB_2023_consolidated|7"},
)
check("the ticker filter is case-insensitive",
      lookup.search_rows(ALL, "chi phí thuế", ticker="vcb") == lookup.search_rows(ALL, "chi phí thuế", ticker="VCB"))
check(
    "the year filter excludes other years",
    {h.table_id for h in lookup.search_rows(ALL, "chi phí thuế", year=2023)} == {"VCB_2023_consolidated|7"},
)
check(
    "the statement_type filter excludes other statements",
    {h.table_id for h in lookup.search_rows(ALL, "chi phí thuế", statement_type="income_statement")}
    == {"TCB_2024_consolidated|41"},
)
check("filters that match nothing return nothing", lookup.search_rows(ALL, "chi phí thuế", ticker="HPG") == [])
check("limit caps the result", len(lookup.search_rows(ALL, "chi phí thuế TNDN hiện hành", limit=2)) == 2)
check("a duplicated table id is scanned once",
      len(lookup.search_rows(ALL + ALL, "chi phí thuế TNDN hiện hành")) == len(hits))


# ── rendering ───────────────────────────────────────────────────────────────
text = lookup.render_hits(hits, {"TCB_2024_consolidated|41": "df4", "VCB_2023_consolidated|7": "df5"})
check("the render binds each table to its variable", "df4 = TCB_2024_consolidated|41" in text)
check("the render prints the position the query will use", "[1] " + TOTAL_LABEL in text)
check("the render prints column names verbatim", "Năm trước: 1.200" in text)
check("each table's header appears once", text.count("df4 = ") == 1)
check("no hits renders a sentence, not an empty string", lookup.render_hits([], {}) != "")

print("tất cả PASS")
