"""Two complementary measurements of the graph REPL, both via LIVE retrieval
(understand → retrieve → load → repl_solver — the real graph prefix, forced to
end at the prompt-fixed REPL instead of routing to lookup/formula).

A) REGRESSION (the risk of collapsing to REPL-only): sample planner-CORRECT
   questions from the 0.2688 run (planner=True, status=ok) and check REPL
   reproduces the planner's answer (rel<0.01). No external gold exists for these,
   so the planner's own answer is the reference — these are mostly simple lookups
   the planner nails deterministically, so agreement ≈ "REPL is a safe replacement".

B) UPSIDE (rescue): the 20 gold questions (real ground truth), ALL of which are
   among the 239 planner-blanks → currently score 0. Check REPL rescues them.

    PYTHONPATH=src .venv_bge/bin/python scripts/measure_repl_rescue.py [n_sample]
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.graph import make_initial_state
from finance_qa.modules.data.service import load_node as load
from finance_qa.modules.rag.service import make_retrieve_node as make_retrieve
from finance_qa.agents.finance.solvers.repl import repl_solver
from finance_qa.agents.finance.understand import make_understand

CFG = FinanceAgentConfig()
_understand = make_understand(CFG)
_retrieve = make_retrieve(CFG)


def _load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def live_repl(qid: int, question: str):
    """Real graph prefix (live retrieval), forced to end at repl_solver."""
    st = make_initial_state(qid, question)
    st.update(_understand(st))
    st.update(_retrieve(st))
    st.update(load(st))
    tids = st.get("table_ids") or []
    if not st.get("frames"):
        return None, tids, "no frames"
    patch = repl_solver(st)
    return patch.get("answer"), tids, ""


def _match(pred, ref) -> bool:
    if pred is None:
        return False
    pred = float(pred)
    return abs(pred - ref) / abs(ref) < 0.01 if abs(ref) > 1e-9 else abs(pred) < 1e-9


def _classify(pred, ref) -> str:
    """Bucket a FAILURE by comparing pred vs ref numerically — no code needed.
      give-up  : pred is None / ≈0 (the model never produced an answer)   → loop/None-helper
      order    : pred ≈ -ref (right magnitude, wrong sign)                → A−B vs B−A (#3)
      unit     : |pred/ref| ≈ 10^k (right number, wrong scale)            → unit conv (#2)
      grounding: none of the above (pulled the wrong cell entirely)       → #1
    """
    if pred is None or abs(float(pred)) < 1e-9:
        return "give-up"
    pred = float(pred)
    if abs(ref) < 1e-9:
        return "grounding"
    if abs(pred + ref) / abs(ref) < 0.02:
        return "order"
    r = abs(pred / ref)
    if r > 0:
        import math
        k = round(math.log10(r))
        if k != 0 and abs(math.log10(r) - k) < 0.03:
            return "unit"
    return "grounding"


def run_block(title, items, ref_label, sink):
    """items: list of (qid, question, ref_answer). Appends per-row dicts to sink."""
    print(f"\n===== {title} =====")
    print(f"{'qid':>4} {'match':>5} {'sec':>4}  {ref_label:>14}  {'repl_pred':>15}  {'why':>9}  note")
    print("-" * 104)
    n_ok = 0
    cats: dict[str, int] = {}
    for qid, question, ref in items:
        t0 = time.monotonic()
        try:
            ans, tids, note = live_repl(qid, question)
        except Exception as exc:  # noqa: BLE001
            ans, tids, note = None, [], f"EXC {exc}"[:40]
        dt = time.monotonic() - t0
        ok = _match(ans, ref)
        n_ok += ok
        why = "" if ok else _classify(ans, ref)
        if not ok:
            cats[why] = cats.get(why, 0) + 1
        pred = "None" if ans is None else f"{float(ans):.6g}"
        print(f"{qid:>4} {('OK' if ok else '·'):>5} {dt:>4.0f}  {ref:>14.6g}  {pred:>15}  {why:>9}  {note}")
        sink.append({"block": title[:1], "qid": qid, "ref": ref,
                     "pred": None if ans is None else float(ans),
                     "ok": bool(ok), "why": why, "sec": round(dt, 1),
                     "tables": tids, "note": note, "question": question})
    print("-" * 104)
    summary = "  ".join(f"{k}={v}" for k, v in sorted(cats.items()))
    print(f"{title}: {n_ok}/{len(items)} = {100*n_ok/len(items):.0f}%   fails: {summary or '—'}")
    return n_ok, len(items)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    run = _load_jsonl("artifacts/runs/full_1012.jsonl")

    # A) planner-correct sample — spread evenly across the sorted planner-ok ids
    planner_ok = [r for r in run if r.get("planner") and r["status"] == "ok"
                  and isinstance(r.get("answer"), (int, float)) and abs(r["answer"]) > 1e-9]
    planner_ok.sort(key=lambda r: r["id"])
    step = max(1, len(planner_ok) // n)
    sampleA = [(r["id"], r["question"], float(r["answer"])) for r in planner_ok[::step][:n]]

    # B) gold blanks
    gold = _load_jsonl("data/eval/extended_gold.jsonl")
    sampleB = [(r["id"], r["question"], float(r["answer"])) for r in gold]

    print(f"planner-ok pool={len(planner_ok)}  → sampling {len(sampleA)} (every {step}th)")
    sink: list = []
    a_ok, a_n = run_block("A REGRESSION (planner-ok → live REPL, ref=planner answer)", sampleA, "planner_ans", sink)
    b_ok, b_n = run_block("B UPSIDE (gold-blank → live REPL, ref=gold)", sampleB, "gold", sink)

    out_path = "artifacts/runs/measure_repl_rescue.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in sink:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Failure-mode tally across BOTH blocks — which lever is biggest?
    fails = [r for r in sink if not r["ok"]]
    cats: dict[str, int] = {}
    for r in fails:
        cats[r["why"]] = cats.get(r["why"], 0) + 1

    print("\n========== SUMMARY ==========")
    print(f"A regression: REPL kept {a_ok}/{a_n} of the planner's wins  "
          f"→ {100*a_ok/a_n:.0f}% (higher = safer to collapse to REPL-only)")
    print(f"B upside:     REPL rescued {b_ok}/{b_n} planner-blanks       "
          f"→ {100*b_ok/b_n:.0f}% (each one is +score, was guaranteed 0)")
    print(f"\nFAILURE MODES across {len(fails)} fails (which to fix first):")
    for k, v in sorted(cats.items(), key=lambda kv: -kv[1]):
        print(f"  {k:>9}: {v:>2}  ({100*v/len(fails):.0f}%)")
    print(f"\nper-row detail → {out_path}")


if __name__ == "__main__":
    main()
