"""Checks for the year-selection rewrite in scripts/pipeline/deliteralize_years.py.

  .venv_bge/bin/python tests/test_year_selection.py

Two halves, same shape as test_count_queries.py. The unit half pins the `* 0`
detector against the real queries from both emit sites and pins the conditions
under which `rebuilt` refuses to rebuild. The sweep half replays a full-1012 run
and reports how many of the annihilated-year queries rebuild into a genuine
selection that reproduces the submitted answer: the claim of the change is that
it moves no answer at all, and that is only worth anything if it is measured.

The sweep needs `artifacts/runs/full1012_v17_unitfix.jsonl`, which is gitignored
(see docs/DATA.md). It is skipped, not failed, when the file is absent.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "pipeline"))

from deliteralize_years import annihilated_year, rebuilt
from finance_qa.modules.tools.python_exec import run_query
from repair_cell_indices import shipped_frame

RUN = Path(__file__).parents[1] / "artifacts/runs/full1012_v17_unitfix.jsonl"

# Verbatim from the submitted run. The first two come from raw_selection_linker,
# the third from project_year in codegen, the fourth is project_year's output
# after apply_units has wrapped it in the abs() it adds to a magnitude answer.
ANNIHILATED = [
    "(df2.iloc[11]['Năm 2021']) * 0 + 2021",
    "((df3.iloc[1]['Số cuối năm'] + df3.iloc[2]['Số cuối năm'])) * 0 + 2024",
    '(df1.iloc[7]["Năm nay"]) * 0 + 2023',
    "abs((abs(df1.iloc[17]['Tại ngày 31 tháng 12 năm | 2018 VND'])) * 0 + 2018)",
]

INTACT = [
    'float(df1.iloc[0]["2018VND"])',
    '(df1.iloc[2]["Năm 2022"] / df1.iloc[18]["Năm 2022"]) * 100',
    # a real multiplication by a small factor, not an annihilation
    '(df1.iloc[3]["Năm nay"]) * 0.01',
    # the rewrite's own output must not read as annihilated, or a second pass
    # over an already-fixed file would loop
    "max([(float(df1.iloc[11]['Năm nay']), 2016), (float(df2.iloc[11]['Năm 2021']), 2021)])[1]",
]


def _diag(slots, *, order="max", kind="cell", axis="year", answer_kind="selected_year"):
    chosen = []
    for year, row in slots:
        cell = {
            "table_id": f"T_{year}|1",
            "row_position": row,
            "column": "Năm nay",
            "value": float(row),
        }
        if kind == "group":
            chosen.append({"kind": "group", "year": year, "cells": [cell, dict(cell)]})
        else:
            chosen.append({"kind": "cell", "year": year, **cell})
    return {"answer_kind": answer_kind, "axis": axis, "order": order, "chosen": chosen}


def unit_half() -> int:
    bad = 0
    for query in ANNIHILATED:
        if not annihilated_year(query):
            bad += 1
            print(f"FAIL annihilated_year said False on a hardcoded year:\n  {query}")
    for query in INTACT:
        if annihilated_year(query):
            bad += 1
            print(f"FAIL annihilated_year said True on a real query:\n  {query}")

    tables: dict[str, str] = {}
    got = rebuilt(_diag([(2016, 3), (2021, 4)]), tables)
    want = "max([(float(df1.iloc[3]['Năm nay']), 2016), (float(df2.iloc[4]['Năm nay']), 2021)])[1]"
    if got != want:
        bad += 1
        print(f"FAIL rebuilt shape:\n  got  {got}\n  want {want}")
    if list(tables) != ["T_2016|1", "T_2021|1"]:
        bad += 1
        print(f"FAIL rebuilt did not record both tables: {tables}")

    # A group slot sums its cells inside the term, so the comparison stays per-year.
    got = rebuilt(_diag([(2016, 3), (2021, 4)], kind="group"), {})
    if got is None or got.count("+") != 2 or not got.startswith("max(["):
        bad += 1
        print(f"FAIL rebuilt did not sum a row group: {got}")

    # `min` questions ("thấp nhất") must not silently become `max`.
    got = rebuilt(_diag([(2016, 3), (2021, 4)], order="min"), {})
    if got is None or not got.startswith("min(["):
        bad += 1
        print(f"FAIL rebuilt ignored the min order: {got}")

    # Refusals. Each of these would produce a query that is not a year selection.
    refuse = {
        "one slot": _diag([(2016, 3)]),
        "duplicate year": _diag([(2016, 3), (2016, 4)]),
        "not a year axis": _diag([(2016, 3), (2021, 4)], axis="ticker"),
        "not a selected year": _diag([(2016, 3), (2021, 4)], answer_kind="value"),
        "unknown order": _diag([(2016, 3), (2021, 4)], order="first"),
        "no diag at all": {},
    }
    for why, diag in refuse.items():
        if rebuilt(diag, {}) is not None:
            bad += 1
            print(f"FAIL rebuilt should refuse when there is {why}")
    return bad


def sweep_half() -> int:
    if not RUN.exists():
        print(f"SKIP sweep: {RUN.name} not present")
        return 0
    rows = [json.loads(line) for line in RUN.read_text(encoding="utf-8").splitlines() if line.strip()]

    flagged, rewrote, moved, refused = [], [], [], []
    for row in rows:
        item = row["item"]
        query = str(item.get("pandas_query") or "")
        if not query or not annihilated_year(query):
            continue
        flagged.append(row["id"])
        tables: dict[str, str] = {}
        new_query = rebuilt((row.get("diag") or {}).get("raw_selection_linker") or {}, tables)
        if new_query is None:
            refused.append(row["id"])
            continue
        try:
            frames = {var: shipped_frame(tid) for tid, var in tables.items()}
            value = float(run_query(new_query, frames))
        except Exception:  # noqa: BLE001 - a query that will not run is the datum
            refused.append(row["id"])
            continue
        answer = float(item["answer"])
        if math.isclose(value, answer, rel_tol=1e-6, abs_tol=1e-9):
            rewrote.append(row["id"])
        else:
            moved.append((row["id"], answer, value))

    print(f"\nsweep over {len(rows)} submitted queries")
    print(f"  hardcoded years   : {len(flagged)}")
    print(f"  rebuilt, same ans : {len(rewrote)}  {rewrote}")
    print(f"  cannot rebuild    : {len(refused)}  {refused}")
    print(f"  answer would move : {len(moved)}  {moved}")
    # The gate in the script skips these, so they are reported, not failed: a moved
    # answer is a signal that the recorded cells no longer match the shipped frame.
    return 0


if __name__ == "__main__":
    failures = unit_half() + sweep_half()
    print("\nOK" if failures == 0 else f"\n{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)
