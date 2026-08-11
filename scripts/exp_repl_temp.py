"""REPL-only, sufficient-table experiment: temp=0 vs temp=0.7.

Uses clean-gold ORACLE tables (gt_tables) so retrieval is NOT a blocker — the
tables are guaranteed to contain the needed data. Forces the REPL path
(use_planner=False) to isolate REPL behaviour, and compares two temperatures.

    PYTHONPATH=src .venv_bge/bin/python scripts/exp_repl_temp.py 44 100 524 582
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, "src")

from finance_qa.modules.codegen.generator import generate

QIDS = [int(x) for x in sys.argv[1:]] or [44, 100, 524, 582]
TEMPS = [float(x) for x in os.environ.get("TEMPS", "0.7").split(",")]


def load_cases():
    answers = {a["qid"]: a for a in json.load(open("data/eval/planner_answers.json"))}
    evalset = {x["qid"]: x for x in json.load(open("data/eval/evalset.json"))}
    cases = {}
    for qid in QIDS:
        if qid not in answers or qid not in evalset:
            continue
        ev = evalset[qid]
        cases[qid] = {
            "question": ev["question"],
            "tables": [t for group in ev["gt_tables"] for t in group],
            "expected": answers[qid]["expected"],
            "abs_tol": answers[qid]["abs_tolerance"],
            "rel_tol": answers[qid]["rel_tolerance"],
        }
    return cases


def is_match(pred, e, at, rt):
    try:
        return abs(float(pred) - e) <= max(at, rt * abs(e), 0.01 * abs(e))
    except (TypeError, ValueError):
        return False


def main():
    cases = load_cases()
    print(f"{'qid':>4} {'temp':>4} {'match':>5} {'steps':>5} {'sec':>5}  {'expected':>12}  answer")
    print("-" * 82)
    tally = {t: 0 for t in TEMPS}
    for qid, c in cases.items():
        for temp in TEMPS:
            os.environ["REPL_TEMP"] = str(temp)
            t0 = time.monotonic()
            res = generate(c["question"], c["tables"], thinking=False, use_planner=False)
            dt = time.monotonic() - t0
            ok = is_match(res.get("answer"), c["expected"], c["abs_tol"], c["rel_tol"])
            tally[temp] += ok
            print(f"{qid:>4} {temp:>4} {'✓' if ok else '·':>5} "
                  f"{str(res.get('repl_steps','')):>5} {dt:>5.0f}  "
                  f"{c['expected']:>12.6g}  {res.get('answer')}")
        print()
    print("-" * 82)
    n = len(cases)
    for t in TEMPS:
        print(f"temp={t}: {tally[t]}/{n}")


if __name__ == "__main__":
    main()
