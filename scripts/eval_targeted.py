"""Targeted eval: 5 questions per difficulty band (L3-like / L5-like / L6-like).
Uses full retrieval tables from full_1012.jsonl.

    PYTHONPATH=src .venv_bge/bin/python -u scripts/eval_targeted.py
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

from finance_qa.modules.codegen.generator import generate

# Gold answers (combined from eval_clean_fullchain + extended_gold)
FULLCHAIN_GOLD = {
    582: 13.7497,
    605: -20.734,
    752: -3903526.0,
    754: 116644397.0,
    818: 145.134,
    820: 4.069037,
    524: 102.424213974,
    363: 3.319357071984094,
}

EXTENDED_GOLD = {}
for line in open("data/eval/extended_gold.jsonl"):
    r = json.loads(line)
    EXTENDED_GOLD[r["id"]] = r["answer"]

GOLD = {**EXTENDED_GOLD, **FULLCHAIN_GOLD}

# Grouped by difficulty (based on formula complexity)
GROUPS = {
    "L3-like (simple ratio / single step)": [582, 605, 390, 415, 407],
    "L5-like (argmax → ratio / statistical)": [381, 392, 422, 424, 426],
    "L6-like (compound: argmax condition → second ratio)": [363, 371, 378, 387, 440],
}


def load_meta():
    meta = {}
    for line in open("artifacts/runs/full_1012.jsonl"):
        r = json.loads(line)
        if r["id"] in GOLD:
            meta[r["id"]] = (r["question"], r.get("table_ids", []))
    return meta


def run_group(name: str, qids: list[int], meta: dict) -> tuple[int, int]:
    print(f"\n{'━'*72}")
    print(f"  {name}")
    print(f"{'━'*72}")
    print(f"  {'qid':>4} {'match':>5} {'path':>8} {'sec':>5}  {'expected':>14}  pred")
    print(f"  {'-'*68}")
    ok = n = 0
    for qid in qids:
        if qid not in meta:
            print(f"  {qid:>4}  (no table_ids)")
            continue
        if qid not in GOLD:
            print(f"  {qid:>4}  (no gold answer)")
            continue
        question, tids = meta[qid]
        expected = GOLD[qid]
        n += 1
        t0 = time.monotonic()
        try:
            res = generate(question, tids, thinking=False, fallback=True)
        except Exception as exc:
            dt = time.monotonic() - t0
            print(f"  {qid:>4} {'·':>5} {'EXC':>8} {dt:>5.0f}  {expected:>14.6g}  {str(exc)[:30]}")
            continue
        dt = time.monotonic() - t0
        ans = res.get("answer")
        err = res.get("error", "")
        path = "planner" if res.get("planner") else ("repl" if res.get("repl") else "?")
        if err or ans is None:
            pred_str = f"ERR: {str(err)[:22]}"
            match = "·"
        else:
            rel = abs(float(ans) - expected) / abs(expected) if abs(expected) > 1e-9 else abs(float(ans))
            match = "OK" if rel < 0.01 else "·"
            if rel < 0.01:
                ok += 1
            pred_str = f"{ans:.6g}"
        print(f"  {qid:>4} {match:>5} {path:>8} {dt:>5.0f}  {expected:>14.6g}  {pred_str}")
    print(f"  {'-'*68}")
    print(f"  → {ok}/{n}")
    return ok, n


def main():
    meta = load_meta()
    total_ok = total_n = 0
    for name, qids in GROUPS.items():
        ok, n = run_group(name, qids, meta)
        total_ok += ok
        total_n += n
    print(f"\n{'='*72}")
    print(f"TOTAL: {total_ok}/{total_n}  ({100*total_ok/total_n:.0f}%)")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
