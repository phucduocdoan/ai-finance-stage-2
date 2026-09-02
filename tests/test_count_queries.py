"""Checks for the count-query guard in execute.py, plus a blast-radius sweep.

  .venv_bge/bin/python tests/test_count_queries.py

Two halves. The unit half pins `is_count_query`/`canonical_count` against the
real queries that motivated them, taken from `artifacts/runs/`. The sweep half
replays every submitted query in a full-1012 run file and reports which answers
the guard changes: the point of the change is that it moves the handful of
counting questions and leaves everything else byte-identical, and that claim is
only worth anything if it is measured rather than asserted.

The sweep needs `artifacts/runs/full1012_v17_unitfix.jsonl`, which is gitignored
(see docs/DATA.md). It is skipped, not failed, when the file is absent.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.codegen.execute import canonical_count, is_count_query
from finance_qa.modules.solve.common.units import strip_scale_factor

RUN = Path(__file__).parents[1] / "artifacts/runs/full1012_v17_unitfix.jsonl"

# Real queries, verbatim from the run files. Shortened only by dropping the
# scale factor `apply_units` would have stripped before reaching the guard.
COUNTS = [
    # q823: four years compared against a 40 tỷ threshold, summed as bare bools
    '((df3.iloc[3]["LNST chưa phân phối VND"] > 40e9) + (df3.iloc[9]["LNST chưa phân phối VND"] > 40e9))',
    # q949: three banks, an `.sum()` wrapped around a scalar addition
    '(((df1.iloc[6]["Năm 2025 Triệu VND"] > 1000) + (df2.iloc[6]["Năm 2025 triệu đồng"] > 1000)).sum())',
    # q966: the model did remember int(), so only the unit guard is needed here
    '((int(df1.iloc[16]["Năm nay"] > 1e12) + int(df3.iloc[15]["Current year"] > 1e12)))',
    # q913: to_numeric around each cell, still a sum of comparisons
    '(((pd.to_numeric(df1.iloc[4]["Số cuối năm"], errors="coerce") > 1e9)'
    ' + (pd.to_numeric(df2.iloc[5]["VND Số cuối năm"], errors="coerce") > 1e9)).sum())',
    # q577: a conjunction, not a sum. Dimensionless all the same.
    '(df1.iloc[2]["Năm 2022"] / df1.iloc[18]["Năm 2022"] > 0.1 and df2.iloc[2]["Năm 2023"] > 0.1)',
    # q932: `abs()` around the count, which is what apply_units itself adds
    '(abs(((df2.iloc[1]["31/12/2020triêu đồng"] > 40000) + (df3.iloc[2]["Số cuối nămTriệu đồng"] > 40000)).sum()))',
    # a count over rows. Dimensionless, so the unit guard must fire; the rewrite
    # must not, and that is asserted separately below.
    '(df1["Năm nay"] > 5).sum()',
    # q435 as the model actually wrote it live: builtin sum over a list of int()s,
    # wrapped in the abs() apply_units adds. Already counting correctly, so only
    # the unit guard has anything to do here.
    "abs(sum([int(df1.iloc[2]['Năm nay'] * 0.9 < 1.5), int(df2.iloc[3]['Năm 2023'] * 0.9 < 1.5)]))",
]

QUANTITIES = [
    # a plain cell read
    'float(df1.iloc[0]["2018VND"])',
    # money added up: an addition tree, but over quantities
    '(df1.iloc[3]["Năm nay"] + df2.iloc[3]["Năm nay"])',
    # a ratio
    '(df1.iloc[2]["Năm 2022"] / df1.iloc[18]["Năm 2022"]) * 100',
    # an average of four ratios (q955 in _is_data_ratio's docstring)
    '((df1.iloc[0]["a"]/df1.iloc[1]["a"]) + (df2.iloc[0]["a"]/df2.iloc[1]["a"])) / 2',
    # a max over cells
    'max(df1.iloc[2]["Năm 2022"], df2.iloc[2]["Năm 2023"])',
    # money added up through builtin sum, which must not read as a count
    "sum([df1.iloc[2]['a'], df2.iloc[3]['a']])",
    # one condition and one quantity: mixed, so not a count
    "sum([int(df1.iloc[2]['a']), df2.iloc[3]['a']])",
    # sum over a Series of amounts
    "sum(df1['a'])",
]


def unit_half() -> int:
    bad = 0
    for query in COUNTS:
        if not is_count_query(query):
            print(f"FAIL is_count_query said False on a count:\n  {query}")
            bad += 1
    for query in QUANTITIES:
        if is_count_query(query):
            print(f"FAIL is_count_query said True on a quantity:\n  {query}")
            bad += 1

    # The saturation fix: bare bool addition must become integer addition.
    saturating = COUNTS[0]
    got = canonical_count(saturating)
    if got is None or "int(" not in got or "+" not in got:
        print(f"FAIL canonical_count did not rewrite the saturating sum: {got!r}")
        bad += 1

    # A row-count is left alone: one leaf, and the Series cannot be int()-wrapped.
    if canonical_count('(df1["Năm nay"] > 5).sum()') is not None:
        print("FAIL canonical_count rewrote a row-count, which would break on a Series")
        bad += 1

    # numpy's `+` on booleans is logical or. This is the whole reason for the fix,
    # so it is pinned here: if a numpy release ever changes it, this test says so.
    import numpy as np

    if (np.bool_(True) + np.bool_(True)) is not np.True_:
        print("NOTE numpy no longer saturates bool addition; canonical_count may be moot")
    if int(np.bool_(True)) + int(np.bool_(True)) != 2:
        print("FAIL int() around a numpy bool no longer counts")
        bad += 1
    return bad


def _frames(item: dict) -> dict:
    out: dict[str, pd.DataFrame] = {}
    for ev in item.get("evidence") or []:
        match = re.match(r"data/(.+)_table_(\d+)\.csv$", ev.get("csv_path", ""))
        if match:
            out[ev["variable"]] = load_frame(f"{match.group(1)}|{match.group(2)}")
    return out


def _value(query: str, env: dict):
    try:
        return float(eval(query, {"__builtins__": __builtins__}, env))  # noqa: S307
    except Exception as exc:  # noqa: BLE001 - a query that will not run is the datum
        return f"{type(exc).__name__}"


def sweep_half() -> int:
    if not RUN.exists():
        print(f"SKIP sweep: {RUN.name} not present")
        return 0
    rows = [json.loads(line) for line in RUN.read_text().splitlines() if line.strip()]
    flagged, changed, broken = [], [], []
    for row in rows:
        item = row["item"]
        query = item.get("pandas_query") or ""
        if not query:
            continue
        raw, _ = strip_scale_factor(query)
        if not is_count_query(raw):
            continue
        rewritten = canonical_count(raw) or raw
        flagged.append(row["id"])
        env = _frames(item)
        env["pd"] = pd
        before, after = _value(query, env), _value(rewritten, env)
        if isinstance(before, float) and isinstance(after, str):
            broken.append((row["id"], before, after))
        if before != after:
            changed.append((row["id"], item.get("answer"), before, after))

    print(f"\nsweep over {len(rows)} submitted queries")
    print(f"  flagged as counts : {len(flagged)}  {flagged}")
    print(f"  answer would move : {len(changed)}")
    for qid, submitted, before, after in changed:
        print(f"    q{qid:>4}  đã nộp={submitted!r}  chạy lại={before!r}  ->  {after!r}")
    print(f"  untouched         : {len(rows) - len(flagged)}")
    if broken:
        print(f"  FAIL rewrite broke a query that used to run: {broken}")
    return len(broken)


if __name__ == "__main__":
    failures = unit_half() + sweep_half()
    print("\nOK" if failures == 0 else f"\n{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)
