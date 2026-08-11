"""Clean-reasoning probe over the FULL chain (planner -> validator -> repair ->
repl), on gt_tables so retrieval is correct by construction. Measures whether the
whole src planning stack rescues the weak model, and which path answered.

    PYTHONPATH=src .venv_bge/bin/python3 scripts/eval_clean_fullchain.py
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from finance_qa.modules.codegen.generator import generate

GOLD = {
    363: 3.319357071984094,
    524: 102.424213974,
    582: 13.7497,
    605: -20.734,
    752: -3903526.0,
    754: 116644397.0,
    818: 145.134,
    820: 4.069037,
}


def main() -> None:
    ev = {e["qid"]: e for e in json.load(open("data/eval/evalset.json", encoding="utf-8"))}
    print(f"{'qid':>4} {'lvl':<5} {'gold':>15} {'pred':>17} {'path':<8} result")
    print("-" * 72)
    ok = 0
    for qid in sorted(GOLD):
        e = ev[qid]
        table_ids = [t for grp in e["gt_tables"] for t in grp]
        try:
            out = generate(e["question"], table_ids, use_planner=True)
        except Exception as exc:  # noqa: BLE001
            print(f"{qid:>4} {e['level']:<5} {'':>15} {'EXC':>17} {'':<8} {str(exc)[:30]}")
            continue
        pred = out.get("answer")
        path = "planner" if out.get("planner") else ("repl" if out.get("repl") else "?")
        g = GOLD[qid]
        err = out.get("error", "")
        if err or not pred:
            res = f"ERR {str(err)[:26]}"
        else:
            rel = abs(pred - g) / abs(g) if abs(g) > 1e-9 else abs(pred)
            res = "OK" if rel < 0.01 else f"x {rel:.0%}"
            if rel < 0.01:
                ok += 1
        print(f"{qid:>4} {e['level']:<5} {g:>15.6g} {str(pred):>17} {path:<8} {res}")
    print("-" * 72)
    print(f"FULL CHAIN (gt_tables, planner+repair+repl): {ok}/{len(GOLD)}")


if __name__ == "__main__":
    main()
