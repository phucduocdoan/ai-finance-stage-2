"""Full graph pipeline eval over the 20 hard gold questions.

Runs run_question() (the LangGraph with formula_solver) for each gold id and
reports which solver produced the answer and whether it matches gold.

    PYTHONPATH=src .venv_bge/bin/python scripts/eval_graph20.py
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

from finance_qa.graph.graph import run_question


def main() -> None:
    gold = {}
    for line in open("data/eval/extended_gold.jsonl"):
        r = json.loads(line)
        gold[int(r["id"])] = (r["question"], float(r["answer"]))

    qids = sorted(gold)
    print(f"{'qid':>4} {'match':>5} {'solver':>14} {'sec':>5}  {'expected':>14}  pred")
    print("-" * 82)

    n_ok = 0
    by_solver: dict[str, list] = {}
    for qid in qids:
        question, expected = gold[qid]
        t0 = time.monotonic()
        try:
            st = run_question(qid, question)
            ans = st.get("answer")
            solver = st.get("solver", "?")
        except Exception as exc:  # noqa: BLE001
            dt = time.monotonic() - t0
            print(f"{qid:>4} {'EXC':>5} {'?':>14} {dt:>5.0f}  {expected:>14.6g}  {str(exc)[:30]}")
            continue
        dt = time.monotonic() - t0

        if ans is None:
            ok = False
        else:
            rel = abs(float(ans) - expected) / abs(expected) if abs(expected) > 1e-9 else abs(float(ans))
            ok = rel < 0.01
        if ok:
            n_ok += 1
        by_solver.setdefault(solver, []).append((qid, ok))
        mark = "OK" if ok else "·"
        print(f"{qid:>4} {mark:>5} {solver:>14} {dt:>5.0f}  {expected:>14.6g}  {ans}")

    print("-" * 82)
    print(f"GRAPH20: {n_ok}/{len(qids)}")
    print("\nBy solver:")
    for s, items in sorted(by_solver.items()):
        oks = sum(1 for _, ok in items if ok)
        ids = ",".join(str(q) for q, _ in items)
        print(f"  {s:>14}: {oks}/{len(items)}  [{ids}]")


if __name__ == "__main__":
    main()
