"""Pure helpers shared across agent nodes (no I/O, no LLM calls)."""
from __future__ import annotations


def expand_years(years: list) -> list[int]:
    """[2016, 2020] with gaps → expand if exactly 2 values spanning a short range."""
    ints = [int(y) for y in years if y]
    if len(ints) == 2 and 1 < ints[1] - ints[0] <= 10:
        return list(range(ints[0], ints[1] + 1))
    return ints
