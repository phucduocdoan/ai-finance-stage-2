"""Hard filter: cut 146,246 tables down to a per-question shortlist.

Semantics are Q4 of docs/investigations/v0_retrieval_pipeline.md:

    keep table if
        table.ticker in q.tickers
    AND table.year   in q.years
    AND ( q.doc_type == "unknown"                        # question didn't say
          OR table.doc_type == q.doc_type
          OR table.doc_type in {aggregated, explanations} )
    AND has_content(table)                               # nothing to retrieve on
    THEN prefer_consolidated(...)                        # only when unknown

`prefer_consolidated` was added after measuring the eval set: enrich returns
`doc_type = "unknown"` for 12 of the 15 table-tier questions, so the doc_type leg
above degrades to `ticker AND year` and the shortlist fills with wrong-scope
duplicates. On #605 that put 50 `separate` tables ahead of a `consolidated` GT,
pushing it to pool rank 50. In all 9 of those questions whose GT has a scope, the
GT is consolidated -- which is the sane default, since a question that does not
say "công ty mẹ" / "riêng" is asking about the group.

Four details that are not obvious and each cost recall when got wrong:

- `q.years` must already have ranges expanded ("2016-2020" -> 5 years), which
  enrich_questions.py does.
- `aggregated` always passes. It means the report filename carries no
  `_consolidated` / `_separate` suffix, which for a standalone company *is* the
  separate report. Without the passthrough, #8 / #336 / #786 / #809 ("công ty
  mẹ" for FTS / HND) get zero candidates.
- A missing dimension is dropped rather than intersected to nothing: #464 has no
  ticker ("trong các công ty…"), #412 has no year. 2/1012 questions.
- `prefer_consolidated` drops `separate` per (ticker, year), not globally: a
  ticker that filed consolidated in 2020 but only separate in 2021 must keep
  2021's separate tables, or a multi-year question loses that year entirely.
- `has_content` is the one non-scope leg. It drops OCR fragments that carry no
  retrievable text at all: 9,419 tables corpus-wide (6.4%), ~8.7% of a typical
  candidate slice, and **0 of the 39 GT tables**. Both channels score `doc_text`,
  whose discriminative part is `first_col_labels` (67% of its characters), so a
  table with no row labels can only ever be matched on its boilerplate.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from finance_qa.core.paths import TABLE_METADATA_PATH


METADATA_PATH = TABLE_METADATA_PATH

SCOPE_FREE_DOC_TYPES = {"aggregated", "explanations"}

MIN_ROWS = 2  # a table this short is a split header or a stray caption, not data


def load_tables(path: Path = METADATA_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as fp:
        return [json.loads(line) for line in fp]


def index_by_ticker_year(tables: Iterable[dict]) -> dict[tuple[str, int], list[dict]]:
    """(ticker, year) -> tables. Avoids rescanning 146k rows per question."""
    index: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for t in tables:
        index[(t["ticker"], t["year"])].append(t)
    return index


def scope_ok(table_doc_type: str, q_doc_type: str) -> bool:
    if q_doc_type == "unknown":
        return True
    if table_doc_type in SCOPE_FREE_DOC_TYPES:
        return True
    return table_doc_type == q_doc_type


def has_content(table: dict) -> bool:
    """False for tables nothing downstream can act on.

    Deliberately only these two signals. `is_continuation` (46% of the corpus) and
    "no note_title nor section_title" (18%) look just as droppable but hold 5 and
    21 GT tables respectively -- a continuation page is where the rows a question
    asks about often live. Both metadata fields are always present, so a missing
    one is a corruption worth a KeyError rather than a silent pass.
    """
    return table["num_rows"] > MIN_ROWS and bool(table["first_col_labels"])


def prefer_consolidated(candidates: list[dict]) -> list[dict]:
    """Drop `separate` tables for any (ticker, year) that also has a broader scope.

    Only for `q.doc_type == "unknown"`. `aggregated` counts as broad: it means the
    report has no scope suffix, so it is the company's only report for that year.
    """
    broad = {
        (t["ticker"], t["year"])
        for t in candidates
        if t["doc_type"] == "consolidated" or t["doc_type"] in SCOPE_FREE_DOC_TYPES
    }
    return [
        t for t in candidates
        if t["doc_type"] != "separate" or (t["ticker"], t["year"]) not in broad
    ]


def shortlist(
    q: dict,
    index: dict[tuple[str, int], list[dict]],
    all_tables: list[dict] | None = None,
) -> list[dict]:
    """Candidate tables for one enriched question.

    `all_tables` is only needed to degrade gracefully when the question has no
    ticker or no year; pass it to keep those 2 questions from returning [].
    """
    tickers = q.get("tickers") or []
    years = q.get("years") or []
    q_doc_type = q.get("doc_type", "unknown")

    if tickers and years:
        candidates: list[dict] = []
        for ticker in tickers:
            for year in years:
                candidates.extend(index.get((ticker, year), ()))
    elif all_tables is None:
        candidates = []
    elif tickers:
        wanted = set(tickers)
        candidates = [t for t in all_tables if t["ticker"] in wanted]
    elif years:
        wanted_years = set(years)
        candidates = [t for t in all_tables if t["year"] in wanted_years]
    else:
        candidates = list(all_tables)

    kept = [
        t for t in candidates
        if scope_ok(t["doc_type"], q_doc_type) and has_content(t)
    ]
    if q_doc_type == "unknown":
        kept = prefer_consolidated(kept)
    return kept
