"""Pure helpers shared across agent nodes (no I/O, no LLM calls)."""
from __future__ import annotations

import re

_REPORT_YEAR = re.compile(r"(20\d\d)")


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
    return [
        table_id
        for rank in range(max((len(v) for v in by_year.values()), default=0))
        for group in by_year.values()
        if rank < len(group)
        for table_id in [group[rank]]
    ]


def expand_years(years: list) -> list[int]:
    """[2016, 2020] with gaps → expand if exactly 2 values spanning a short range."""
    ints = [int(y) for y in years if y]
    if len(ints) == 2 and 1 < ints[1] - ints[0] <= 10:
        return list(range(ints[0], ints[1] + 1))
    return ints
