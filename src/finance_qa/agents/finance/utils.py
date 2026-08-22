"""Pure helpers shared across agent nodes (no I/O, no LLM calls)."""
from __future__ import annotations

import re

_REPORT_YEAR = re.compile(r"(20\d\d)")
# `<TICKER>_financial_statements_<year>_consolidated` covers all but three ids in the
# corpus; the exceptions are `<TICKER>_<year>_financial_statement_explanations_1`, so
# the ticker is taken from the front and the year from wherever it falls. Matching only
# the common shape put those three in the no-slot group, where they took a slot of their
# own and pushed a company out of the head (q392 lost OGC that way).
_TICKER = re.compile(r"^([A-Z0-9]+)_")


def _interleave(groups: dict[str, list[str]]) -> list[str]:
    """One table from each group, then the next from each, and so on.

    Rank order inside a group is preserved, and so is first-appearance order of
    the groups, so a question with a single group gets its list back unchanged.
    """
    return [
        table_id
        for rank in range(max((len(v) for v in groups.values()), default=0))
        for group in groups.values()
        if rank < len(group)
        for table_id in [group[rank]]
    ]


def slot_round_robin(table_ids: list[str]) -> list[str]:
    """Re-rank so the head holds one table per company, then one per year each.

    This is `year_round_robin`'s problem one axis wider, and it is where the
    multi-company questions were being lost. Retrieval is not what fails them:
    `table_ids` holds a table for every ticker the question names on 310/310 of
    them (`_evidence` appends every shortlisted primary statement, so the pool's
    ticker coverage carries through). What fails them is the flat
    `[:codegen_max_tables]` slice — the head of three covers every named ticker
    on only 107 of the 310, because ranking sorts by relevance and a screening
    question's tickers are spread down the list at positions 0, 2, 3, 5, 6, 8, 9,
    14, 16, 31 (q432, ten companies).

    Interleaving makes covering k companies cost exactly k tables instead of the
    5 at the median, 12 at p90 and 32 at worst that the plain prefix needs.

    Company is the *outer* axis and year the inner one, which is not a free
    choice. A flat interleave over (ticker, year) pairs takes them in
    first-appearance order, so on q608 — MML and MSN, 2018 and 2023 — the head of
    four came out MML/2018, MML/2023, MML/2022, MML/2019 and never reached MSN:
    the pool carries every year in the expanded range, not just the two the
    question names, so one company can own the whole budget. Nesting guarantees
    every company appears before any company appears twice, which is the right
    priority for a screening question — a missing company makes the answer
    impossible, a missing year usually makes it wrong.
    """
    by_ticker: dict[str, dict[str, list[str]]] = {}
    for table_id in table_ids:
        base = table_id.rsplit("|", 1)[0]
        ticker = _TICKER.match(base)
        year = _REPORT_YEAR.search(base)
        by_ticker.setdefault(ticker.group(1) if ticker else "", {}).setdefault(
            year.group(1) if year else "", []
        ).append(table_id)
    return _interleave({t: _interleave(years) for t, years in by_ticker.items()})


def year_round_robin(table_ids: list[str]) -> list[str]:
    """Re-rank so the head of the list holds one table per year, best year first.

    Retrieval already spreads across years — the judge prompt tells it to pick a
    table for every year the question names, and on the 196 multi-year questions
    that ask for an argmax/argmin over a period it does: its top three sit in
    three different years for 112 of them. What loses the years is the flat
    `[:codegen_max_tables]` slice underneath, because three slots cannot hold the
    five years those questions need at the median.

    Interleaving instead of truncating the ranking is worth more than widening it:
    at five tables it puts every needed year in front of the model for 42% of
    those questions against 32% for the plain prefix, and 42% is 95% of what the
    entire 35-table pool could give (44%). The remaining 56% are missing the years
    from the pool itself, which no re-ranking here can fix.

    Rank order inside a year is preserved, and so is first-appearance order of the
    years, so for a single-year question this returns the list unchanged.
    """
    by_year: dict[str, list[str]] = {}
    for table_id in table_ids:
        match = _REPORT_YEAR.search(table_id.rsplit("|", 1)[0])
        by_year.setdefault(match.group(1) if match else "", []).append(table_id)
    return _interleave(by_year)


def expand_years(years: list) -> list[int]:
    """[2016, 2020] with gaps → expand if exactly 2 values spanning a short range."""
    ints = [int(y) for y in years if y]
    if len(ints) == 2 and 1 < ints[1] - ints[0] <= 10:
        return list(range(ints[0], ints[1] + 1))
    return ints
