"""Trace canonical data available to the current formula service for one question."""

from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from finance_qa.modules.codegen.formula import _collect_canonical
from finance_qa.modules.data.table_store import load_frame


frozen = {
    int(row["id"]): row
    for row in (json.loads(line) for line in open("artifacts/runs/regen_frozen_patched.jsonl", encoding="utf-8"))
}

qid = int(sys.argv[1]) if len(sys.argv) > 1 else 371
row = frozen[qid]
print("Q:", row["question"])
print()

frames, names = {}, {}
for i, table_id in enumerate(row["table_ids"]):
    var = f"df{i + 1}"
    try:
        frames[var] = load_frame(table_id)
        names[var] = table_id
    except Exception as exc:  # noqa: BLE001
        print(f"skip {table_id}: {exc}")

data = _collect_canonical(frames, names)
print("Canonical data:")
for ticker in sorted(data):
    print(f"{ticker}:")
    for year in sorted(data[ticker]):
        metrics = data[ticker][year]
        keys = ", ".join(sorted(metrics)[:40])
        print(f"  {year}: {len(metrics)} metrics: {keys}")
