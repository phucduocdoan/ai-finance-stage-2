"""Say which year each money column holds, deterministically.

Measured over the 225 tables the solver was shown: 196 have money columns, and
110 of those have **no year anywhere in those headers** — they say `Số cuối năm`
/ `Số đầu năm`, or `Tại ngày 31 tháng 12 năm` with the year lost at the line
break. The year is only recoverable from the report year in metadata.

The model cannot do that join. Given `['Tại ngày 31 tháng 12 năm', 'Unnamed: 4']`
it invents a column named `Tại ngày 31 tháng 12 năm 2018` and the query dies with
`KeyError`. Showing it the real column list does not help: it printed that exact
list in a sandbox probe and then fabricated the name anyway.

So the join is done here instead. `Số cuối năm` on a 2018 report is 31/12/2018;
`Số đầu năm` is 31/12/2017. That is a rule, not a judgement call, and it belongs
in code.

Nothing is renamed. The grader re-runs the submitted query against
`load_frame(tid).to_csv(...)`, so the column names the model writes must be the
real ones — this only adds a legend line above the grid.
"""
from __future__ import annotations

import re

import pandas as pd

# A money column: numeric, and big enough that it is amounts rather than codes.
# The `Mã số` column of a balance sheet is numeric too, which is why the
# magnitude test is here and not optional.
_MONEY_MEDIAN = 1e6

_YEAR = re.compile(r"(?:19|20)\d{2}")
# "cuối năm/kỳ", "năm nay", "tại ngày 31 tháng 12" -> the report year itself.
_CURRENT = re.compile(r"cuối\s*(?:năm|kỳ)|năm\s*nay|kỳ\s*này|31\s*tháng\s*12|31/12", re.I)
# "đầu năm/kỳ", "năm trước" -> the year before it.
_PRIOR = re.compile(r"đầu\s*(?:năm|kỳ)|năm\s*trước|kỳ\s*trước|01/01|1\s*tháng\s*1", re.I)


def money_columns(df: pd.DataFrame) -> list:
    return [
        col for col in df.columns
        if pd.api.types.is_numeric_dtype(df[col])
        and df[col].abs().median(skipna=True) > _MONEY_MEDIAN
    ]


def _report_year(table_id: str, meta_year) -> int | None:
    if meta_year:
        try:
            return int(meta_year)
        except (TypeError, ValueError):
            pass
    found = _YEAR.search(table_id)
    return int(found.group(0)) if found else None


def column_years(df: pd.DataFrame, table_id: str, meta_year=None) -> dict:
    """Money column -> the year it holds, as a string. Empty when nothing to add.

    Returns nothing for the 72 tables whose headers already carry the year: the
    grid says it, and repeating it would only be another thing to get wrong.
    """
    year = _report_year(table_id, meta_year)
    if year is None:
        return {}
    money = money_columns(df)
    if not money or all(_YEAR.search(str(col)) for col in money):
        return {}

    resolved: dict = {}
    unlabelled: list = []
    for col in money:
        text = str(col)
        found = _YEAR.search(text)
        if found:
            resolved[col] = found.group(0)
        elif _CURRENT.search(text):
            resolved[col] = str(year)
        elif _PRIOR.search(text):
            resolved[col] = str(year - 1)
        else:
            unlabelled.append(col)

    if not unlabelled:
        return resolved
    if not resolved:
        # Nothing named at all. Vietnamese statements print the current period
        # first, so column order is the only signal and it is a weak one.
        return {col: str(year - i) for i, col in enumerate(unlabelled)}
    if len(money) == 2 and len(unlabelled) == 1 and money[-1] is unlabelled[0]:
        # `['Tại ngày 31 tháng 12 năm', 'Unnamed: 4']`: the second column of a
        # two-period statement is the comparative, one year back.
        anchor = int(resolved[money[0]])
        resolved[unlabelled[0]] = str(anchor - 1)
        return resolved
    for col in unlabelled:
        resolved[col] = "?"
    return resolved


def year_legend(df: pd.DataFrame, table_id: str, meta_year=None) -> str:
    """One prompt line binding each money column to its year, or ``""``."""
    years = column_years(df, table_id, meta_year)
    if not years:
        return ""
    pairs = "; ".join(f"'{col}' = năm {year}" for col, year in years.items())
    return f"Năm của từng cột số tiền (suy ra từ năm báo cáo): {pairs}"


__all__ = ["column_years", "money_columns", "year_legend"]
