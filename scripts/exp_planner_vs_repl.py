"""Who fails on SUFFICIENT tables: the planner, or the REPL?

Uses clean-gold ORACLE tables (retrieval is NOT the blocker) and runs each
question two ways on the SAME tables:
  - planner solo   : generate(use_planner=True,  fallback=False)
  - REPL isolated  : generate(use_planner=False)              [REPL_TEMP knob]

This separates "planner handles it" from "REPL as last resort handles it",
which the full-chain number conflates.

    PYTHONPATH=src .venv_bge/bin/python scripts/exp_planner_vs_repl.py 44 100 524 582
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, "src")

from finance_qa.modules.codegen.generator import generate

QIDS = [int(x) for x in sys.argv[1:]] or [44, 100, 524, 582]
os.environ.setdefault("REPL_TEMP", "0.7")


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


def run(case, **kw):
    t0 = time.monotonic()
    res = generate(case["question"], case["tables"], thinking=False, **kw)
    dt = time.monotonic() - t0
    ok = is_match(res.get("answer"), case["expected"], case["abs_tol"], case["rel_tol"])
    return res, ok, dt


def main():
    cases = load_cases()
    print(f"{'qid':>4}  {'PLANNER':>18}  {'REPL(isolated)':>22}  expected")
    print("-" * 78)
    p_ok = r_ok = 0
    for qid, c in cases.items():
        pres, pmatch, pdt = run(c, use_planner=True, fallback=False)
        rres, rmatch, rdt = run(c, use_planner=False)
        p_ok += pmatch
        r_ok += rmatch
        perr = "" if pmatch else f" err={(pres.get('error') or '')[:40]}"
        pcol = f"{'✓' if pmatch else '·'} {str(pres.get('answer'))[:12]:>12} {pdt:>3.0f}s"
        rcol = f"{'✓' if rmatch else '·'} {str(rres.get('answer'))[:12]:>12} {rres.get('repl_steps','?')}st {rdt:>3.0f}s"
        print(f"{qid:>4}  {pcol:>18}  {rcol:>22}  {c['expected']:.6g}{perr}")
    print("-" * 78)
    n = len(cases)
    print(f"PLANNER solo: {p_ok}/{n}   REPL isolated: {r_ok}/{n}")


if __name__ == "__main__":
    main()
