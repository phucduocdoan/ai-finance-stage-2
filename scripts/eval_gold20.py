"""Full pipeline eval over all 20 gold questions.

Uses table_ids from full_1012.jsonl (retrieval already done) + gold answers
from extended_gold.jsonl. Runs generate() for each and reports path + match.

    PYTHONPATH=src .venv_bge/bin/python scripts/eval_gold20.py
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

from finance_qa.modules.codegen.generator import generate


def load():
    gold = {}
    for line in open("data/eval/extended_gold.jsonl"):
        r = json.loads(line)
        gold[r["id"]] = (r["question"], r["answer"])

    meta = {}
    for line in open("artifacts/runs/full_1012.jsonl"):
        r = json.loads(line)
        if r["id"] in gold:
            meta[r["id"]] = (r["question"], r.get("table_ids", []))

    return gold, meta


def main() -> None:
    gold, meta = load()
    qids = sorted(gold.keys())

    print(f"Running full pipeline on {len(qids)} gold questions...")
    print(f"{'qid':>4} {'match':>5} {'path':>8} {'sec':>5}  {'expected':>14}  pred")
    print("-" * 80)

    n_ok = 0
    n_run = 0
    errors = []

    for qid in qids:
        if qid not in meta:
            print(f"{qid:>4}  (no table_ids in full_1012)")
            continue

        question, tids = meta[qid]
        _, expected = gold[qid]
        n_run += 1

        t0 = time.monotonic()
        try:
            res = generate(question, tids, thinking=False, fallback=True)
        except Exception as exc:
            dt = time.monotonic() - t0
            print(f"{qid:>4} {'·':>5} {'EXC':>8} {dt:>5.0f}  {expected:>14.6g}  {str(exc)[:30]}")
            errors.append((qid, str(exc)))
            continue
        dt = time.monotonic() - t0

        ans = res.get("answer")
        err = res.get("error", "")
        path = "planner" if res.get("planner") else ("repl" if res.get("repl") else "?")

        if err or ans is None:
            ok = False
            pred_str = f"ERR: {str(err)[:25]}"
        else:
            rel = abs(float(ans) - expected) / abs(expected) if abs(expected) > 1e-9 else abs(float(ans))
            ok = rel < 0.01
            pred_str = str(ans)

        if ok:
            n_ok += 1

        mark = "OK" if ok else "·"
        print(f"{qid:>4} {mark:>5} {path:>8} {dt:>5.0f}  {expected:>14.6g}  {pred_str}")

    print("-" * 80)
    print(f"GOLD20: {n_ok}/{n_run}  ({100*n_ok/n_run:.0f}%)  [baseline: 6/20 = 30%]")
    if errors:
        print(f"Exceptions: {len(errors)}")


if __name__ == "__main__":
    main()
