"""Measure the impact of the 4 REPL/exec fixes on hard gold questions.

Runs the full chain generate(thinking=False, fallback=True) on the same hard
extended_gold questions, sequentially (deterministic), and reports path + match.
Baseline before fixes (this session): only q390 correct (1/5).

    PYTHONPATH=src .venv_bge/bin/python scripts/measure_repl_fixes.py 363 415 390 392 424
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

from finance_qa.modules.codegen.generator import generate

QIDS = [int(x) for x in sys.argv[1:]] or [363, 415, 390, 392, 424]


def load():
    exp = {}
    for line in open("data/eval/extended_gold.jsonl"):
        r = json.loads(line)
        exp[r["id"]] = r["answer"]
    meta = {}
    for line in open("artifacts/runs/full_1012.jsonl"):
        r = json.loads(line)
        if r["id"] in exp:
            meta[r["id"]] = (r["question"], r["table_ids"])
    return exp, meta


def main() -> None:
    exp, meta = load()
    print(f"{'qid':>4} {'match':>5} {'path':>8} {'steps':>5} {'sec':>5}  {'expected':>14}  answer")
    print("-" * 90)
    n_ok = 0
    for qid in QIDS:
        if qid not in meta:
            print(f"{qid:>4}  (no cached tables)")
            continue
        question, tids = meta[qid]
        t0 = time.monotonic()
        res = generate(question, tids, thinking=False, fallback=True)
        dt = time.monotonic() - t0
        ans = res.get("answer")
        e = exp[qid]
        ok = ans is not None and abs(float(ans) - e) <= 0.01 * abs(e)
        n_ok += ok
        path = "planner" if res.get("planner") else "REPL"
        steps = res.get("repl_steps") or res.get("attempts") or ""
        print(f"{qid:>4} {'✓' if ok else '·':>5} {path:>8} {str(steps):>5} {dt:>5.0f}  "
              f"{e:>14.6g}  {ans}")
    print("-" * 90)
    print(f"total: {n_ok}/{len([q for q in QIDS if q in meta])}  (baseline before fixes: 1/5)")


if __name__ == "__main__":
    main()
