"""Rewrite a `max`/`min` selection query into one that answers *which year*.

Part of the `codegen.execute` facade: see `execute/__init__.py`.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

import pandas as pd

from finance_qa.modules.solve.common.intent import MIN_MARKER, YEAR_ANSWER_MARKER, intent_norm
from finance_qa.modules.tools.python_exec import run_query

# `max(a, b, c)` where each argument reads exactly one frame. Deliberately not a
# general expression parser: the whole guard rests on knowing which *year* won, and
# that is only well defined when each argument belongs to one year's table.
_SELECT_CALL = re.compile(r"^\s*(max|min)\s*\((?P<args>.+)\)\s*$", re.S)
_ROUND_CALL = re.compile(r"^\s*round\s*\((?P<args>.+)\)\s*$", re.S)
_FRAME_REF = re.compile(r"\bdf\d+\b")
_YEAR_IN_ID = re.compile(r"_(20\d\d)_")
_YEAR_ANYWHERE = re.compile(r"\b(?:19|20)\d\d\b")


def _split_args(args: str) -> list[str] | None:
    """Top-level comma split. None if the brackets do not balance."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(args):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth < 0:
                return None
        elif ch == "," and depth == 0:
            parts.append(args[start:i])
            start = i + 1
    parts.append(args[start:])
    return [p.strip() for p in parts if p.strip()] if depth == 0 else None


def _unwrap_round(query: str) -> str:
    """Look through the `round(expr, 2)` codegen wraps almost everything in.

    978 of the 1,012 queries in the v8 run start with `round(`, and `_SELECT_CALL` is
    anchored, so `project_year` matched none of them and never fired once. q866 submits
    `round(max(...), 2)` and answered with an amount.
    """
    call = _ROUND_CALL.match(query.strip())
    if not call:
        return query
    args = _split_args(call.group("args"))
    if args is None or len(args) > 2:
        return query
    if len(args) == 2 and not args[1].lstrip("-").isdigit():
        return query
    return args[0]


def _year_of(term: str, table_id: str) -> str | None:
    """The year the winning term speaks for.

    The column name wins over the report id, because a 2023 report carries a
    "Năm trước" column holding 2022 and the report id would then name the wrong
    year. Neither is trusted blindly — `project_year` checks the result against the
    years the question actually lists.
    """
    in_column = _YEAR_ANYWHERE.findall(term)
    if in_column:
        return in_column[-1]
    found = _YEAR_IN_ID.search(table_id)
    return found.group(1) if found else None


def project_year(
    query: str,
    frames: Mapping[str, pd.DataFrame],
    names: Mapping[str, str],
    question: str,
) -> tuple[str, str] | None:
    """Turn `max(<2019 cell>, <2022 cell>)` into a query that answers *which year*.

    A "năm nào" question wants a year and codegen submits the winning cell's value
    instead: on the 1,012-question run all 28 such questions answer with an amount,
    which is wrong by definition. `raw_selection_linker` has had the answer all
    along — it emits `(<cell>) * 0 + <year>`, keeping the year inside the *query* so
    that re-executing the submission still yields it. codegen never asked, exactly
    as it never asked `cell_locator` about expense signs.

    Returns `(query, year)` or None. None is the common case and is meant to be:
    the rewrite only fires when the winning year is unambiguous, which means the
    query is a `max`/`min` of single-frame terms, bare or under codegen's `round`
    wrapper, *and* the year it lands on is one the question actually names. That last
    check is what stops a "Năm trước" column from answering 2022 for a question
    about 2023.
    """
    if not YEAR_ANSWER_MARKER.search(intent_norm(question)):
        return None
    call = _SELECT_CALL.match(_unwrap_round(query).strip())
    if not call:
        return None
    args_text = call.group("args").strip()
    # The model writes both `max(a, b)` and `max([a, b])`; q978 is the second form
    # and was silently skipped, because its commas sit one bracket deep. Stripping a
    # wrapping pair is safe: for `max([a, b], [c, d])` the remainder no longer
    # balances and `_split_args` rejects it rather than mis-splitting.
    if args_text.startswith("[") and args_text.endswith("]"):
        args_text = args_text[1:-1]
    args = _split_args(args_text)
    if not args or len(args) < 2:
        return None

    values: dict[str, float] = {}
    for term in args:
        refs = set(_FRAME_REF.findall(term))
        if len(refs) != 1:  # a term spanning two years names no single year
            return None
        try:
            values[term] = float(run_query(term, dict(frames)))
        except Exception:  # noqa: BLE001 - one unreadable cell voids the comparison
            return None
    if len(values) != len(args):
        return None

    pick = min if MIN_MARKER.search(intent_norm(question)) else max
    winner = pick(values, key=lambda term: values[term])
    year = _year_of(winner, names.get(_FRAME_REF.search(winner).group(0), ""))
    asked = set(_YEAR_ANYWHERE.findall(question))
    if not year or year not in asked:
        return None
    order = "min" if pick is min else "max"
    selection = _year_selection(list(values), names, asked, order, frames, year)
    return (selection or f"({winner}) * 0 + {year}"), year


def _year_selection(
    terms: Sequence[str],
    names: Mapping[str, str],
    asked: set[str],
    order: str,
    frames: Mapping[str, pd.DataFrame],
    winning_year: str,
) -> str | None:
    """The `max`/`min` above, rewritten to return the year instead of the amount.

    `project_year` used to emit `(<winning term>) * 0 + <year>` and throw the other
    branches away. Re-executing that reproduces the year, which was the point, but
    `* 0` annihilates the cell it reads, so the year ships as a stored constant --
    what the rules score as zero, and what no constant check can see, because the
    expression still names a frame.

    Keeping every branch keeps the year data-dependent: change a cell and a
    different tuple wins.

    Returns None unless every term resolves to a distinct year the question itself
    names, and the rebuilt query runs and lands on the same year the ranking did.
    The caller falls back to the old shape, so this cannot move an answer -- it can
    only decline. Declining is the common case for a term whose year comes from the
    report id rather than the column, which is exactly where `_year_of` is least
    sure of itself.
    """
    if order not in {"max", "min"} or len(terms) < 2:
        return None
    by_year: dict[str, str] = {}
    for term in terms:
        ref = _FRAME_REF.search(term)
        year = _year_of(term, names.get(ref.group(0), "")) if ref else None
        if not year or year not in asked or year in by_year:
            return None
        by_year[year] = term
    if winning_year not in by_year:
        return None

    body = ", ".join(f"(float({by_year[year]}), {year})" for year in sorted(by_year))
    query = f"{order}([{body}])[1]"
    try:
        if str(int(run_query(query, dict(frames)))) != winning_year:
            return None
    except Exception:  # noqa: BLE001 - a rewrite that will not run is simply refused
        return None
    return query
