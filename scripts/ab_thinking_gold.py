"""A/B the planner's `thinking` flag on the 15 clean-gold questions, oracle-fed.

Single variable = thinking on/off. Same v9f+F9 code, same oracle gt_tables,
verify off (matches base). LLM runs at temperature 0 → deterministic, so a single
pass is reproducible; per-type buckets are tiny (2-4 q) so read them as anecdotes,
the 15-total as the real signal (noise floor ~6.7pp/question).

Run:
    PYTHONPATH=src .venv_bge/bin/python scripts/ab_thinking_gold.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "src")

from finance_qa.planning.generator import generate

WORKERS = 4
CONFIGS = [("A_base(no-think)", False), ("B_think", True)]


def load_cases() -> list[dict]:
    answers = json.load(open("data/eval/planner_answers.json"))
    evalset = {x["qid"]: x for x in json.load(open("data/eval/evalset.json"))}
    cases = []
    for a in answers:
        qid = a["qid"]
        ev = evalset[qid]
        tables = [t for group in ev["gt_tables"] for t in group]
        cases.append({
            "qid": qid,
            "level": ev["level"],
            "type": ev["level"].split(".")[0],  # L1..L6
            "question": ev["question"],
            "tables": tables,
            "expected": a["expected"],
            "abs_tol": a["abs_tolerance"],
            "rel_tol": a["rel_tolerance"],
        })
    return cases


def is_match(pred, exp: float, abs_tol: float, rel_tol: float) -> bool:
    if pred is None:
        return False
    try:
        pred = float(pred)
    except (TypeError, ValueError):
        return False
    return abs(pred - exp) <= max(abs_tol, rel_tol * abs(exp))


def run_config(cases: list[dict], thinking: bool) -> dict[int, dict]:
    def work(c: dict) -> tuple[int, dict]:
        try:
            plan = generate(
                c["question"], c["tables"],
                thinking=thinking, use_planner=True,
            )
            return c["qid"], {"answer": plan.get("answer"), "error": plan.get("error", "")}
        except Exception as exc:  # noqa: BLE001
            return c["qid"], {"answer": None, "error": f"EXC {type(exc).__name__}: {exc}"}

    out: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for qid, res in ex.map(work, cases):
            out[qid] = res
    return out


def main() -> None:
    cases = load_cases()
    by_qid = {c["qid"]: c for c in cases}
    results: dict[str, dict[int, dict]] = {}
    for name, thinking in CONFIGS:
        print(f"running {name} ...", file=sys.stderr, flush=True)
        results[name] = run_config(cases, thinking)

    a_name, b_name = CONFIGS[0][0], CONFIGS[1][0]
    a_res, b_res = results[a_name], results[b_name]

    # per-question detail
    print(f"\n{'qid':>4} {'type':>4} {'A':>3} {'B':>3}  expected        A_ans           B_ans")
    print("-" * 78)
    for c in sorted(cases, key=lambda x: (x["type"], x["qid"])):
        q = c["qid"]
        a_ok = is_match(a_res[q]["answer"], c["expected"], c["abs_tol"], c["rel_tol"])
        b_ok = is_match(b_res[q]["answer"], c["expected"], c["abs_tol"], c["rel_tol"])
        print(f"{q:>4} {c['type']:>4} {'✓' if a_ok else '·':>3} {'✓' if b_ok else '·':>3}  "
              f"{c['expected']:>14.6g}  {str(a_res[q]['answer'])[:14]:>14}  {str(b_res[q]['answer'])[:14]:>14}")

    # per-type buckets
    typ = defaultdict(lambda: [0, 0, 0])  # type -> [n, a_ok, b_ok]
    for c in cases:
        q = c["qid"]
        typ[c["type"]][0] += 1
        typ[c["type"]][1] += is_match(a_res[q]["answer"], c["expected"], c["abs_tol"], c["rel_tol"])
        typ[c["type"]][2] += is_match(b_res[q]["answer"], c["expected"], c["abs_tol"], c["rel_tol"])

    print(f"\n{'type':>6} {'n':>3} {'A_base':>8} {'B_think':>8}  delta")
    print("-" * 40)
    ta = tb = tn = 0
    for t in sorted(typ):
        n, a, b = typ[t]
        tn += n; ta += a; tb += b
        print(f"{t:>6} {n:>3} {a:>4}/{n:<3} {b:>4}/{n:<3}  {b-a:+d}")
    print("-" * 40)
    print(f"{'TOTAL':>6} {tn:>3} {ta:>4}/{tn:<3} {tb:>4}/{tn:<3}  {tb-ta:+d}")
    print(f"\nA_base   {ta}/{tn} = {ta/tn:.0%}")
    print(f"B_think  {tb}/{tn} = {tb/tn:.0%}")


if __name__ == "__main__":
    main()
