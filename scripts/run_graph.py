"""Drive the finance QA graph agent over questions -> pipeline JSONL (+ scoring).

Runs run_question() (understand -> retrieve[LIVE] -> load -> _route -> solver)
for each requested id, converts the final FinanceState into the submission
`item` shape (reusing pipeline.run.submission_item), and appends one record per
question. The JSONL it writes is consumed directly by scripts/build_submission.py
(it reads record["item"] / record["table_ids"]).

This is the ONLY driver that runs the *graph* over many questions -- build_submission
itself only packages; pipeline.run drives the planner pipeline, not the graph.

Usage:
  # gate: mixed labeled set (lookup + formula + multi-step), scored vs gold
  PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --measure \
      --out artifacts/runs/graph_measure.jsonl

  # explicit ids
  PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --ids 1,17,40 --out /tmp/r.jsonl

  # full submission run (~1012)
  PYTHONPATH=src .venv_bge/bin/python scripts/run_graph.py --all \
      --out artifacts/runs/graph_1012.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from finance_qa.agents.finance.graph import make_initial_state, run_question
from finance_qa.core.paths import QUESTION_METADATA_PATH
from finance_qa.pipelines.submission import submission_item


def load_questions() -> dict[int, dict]:
    with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
        return {int(r["id"]): r for r in map(json.loads, filter(str.strip, fh))}


def load_gold() -> dict[int, float]:
    """id -> expected answer, from the two answer-labeled sources we have."""
    gold: dict[int, float] = {}
    pa = Path("data/eval/planner_answers.json")
    if pa.exists():
        for r in json.loads(pa.read_text(encoding="utf-8")):
            gold[int(r["qid"])] = float(r["expected"])
    eg = Path("data/eval/extended_gold.jsonl")
    if eg.exists():
        for line in filter(str.strip, eg.read_text(encoding="utf-8").splitlines()):
            r = json.loads(line)
            gold.setdefault(int(r["id"]), float(r["answer"]))  # extended_gold is formula-only
    return gold


def run_one(qrow: dict) -> dict:
    """One question through the graph -> a build_submission-compatible record."""
    qid = int(qrow["id"])
    t0 = time.monotonic()
    try:
        st = run_question(qid, qrow["question"])
    except Exception as exc:  # noqa: BLE001 - per-question error is data, run continues
        return {
            "id": qid, "question": qrow["question"], "status": "error",
            "error": f"{type(exc).__name__}: {exc}", "table_ids": [],
            "solver": "?", "seconds": round(time.monotonic() - t0, 1),
        }
    table_ids = st.get("table_ids") or []
    plan = {
        "answer": st.get("answer"),
        "evidence": st.get("evidence") or [],
        "pandas_query": st.get("pandas_query") or "0.0",
    }
    return {
        "id": qid,
        "question": qrow["question"],
        "status": "ok",
        "error": "",
        "item": submission_item(qrow, table_ids, plan),
        "table_ids": table_ids,
        "solver": st.get("solver", "?"),
        "seconds": round(time.monotonic() - t0, 1),
    }


def _match(pred, expected: float) -> bool:
    if pred is None:
        return False
    denom = abs(expected) if abs(expected) > 1e-9 else 1.0
    return abs(float(pred) - expected) / denom < 0.01


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="run all 1012 questions")
    grp.add_argument("--ids", help="comma-separated question ids")
    grp.add_argument(
        "--measure", action="store_true",
        help="run the mixed labeled gate set (planner_answers: lookup+formula+multi-step)",
    )
    ap.add_argument("--out", type=Path, required=True, help="output pipeline JSONL")
    ap.add_argument("--limit", type=int, help="cap number of questions (debug)")
    args = ap.parse_args()

    questions = load_questions()
    gold = load_gold()

    if args.all:
        ids = sorted(questions)
    elif args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    else:  # --measure: the labeled gate
        pa = json.loads(Path("data/eval/planner_answers.json").read_text(encoding="utf-8"))
        ids = [int(r["qid"]) for r in pa]
    if args.limit:
        ids = ids[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"running {len(ids)} question(s) through the graph -> {args.out}\n")
    print(f"{'qid':>4} {'match':>5} {'solver':>14} {'sec':>5}  {'expected':>16}  answer")
    print("-" * 92)

    records = []
    with args.out.open("w", encoding="utf-8") as fh:
        for qid in ids:
            rec = run_one(questions[qid])
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            records.append(rec)

            ans = rec.get("item", {}).get("answer") if rec["status"] == "ok" else None
            exp = gold.get(qid)
            if exp is None:
                mark = "-"
            else:
                mark = "OK" if _match(ans, exp) else "·"
            exp_s = f"{exp:.6g}" if exp is not None else "?"
            print(f"{qid:>4} {mark:>5} {rec['solver']:>14} {rec['seconds']:>5.0f}  {exp_s:>16}  {ans}")

    # ── scoring summary (only over ids we have gold for) ─────────────────────
    scored = [r for r in records if r["id"] in gold]
    if scored:
        print("-" * 92)
        n_ok = sum(1 for r in scored if _match(r.get("item", {}).get("answer"), gold[r["id"]]))
        print(f"SCORED: {n_ok}/{len(scored)} match (rel<0.01)   [unscored: {len(records)-len(scored)}]")
        by_solver: dict[str, list] = {}
        for r in scored:
            ok = _match(r.get("item", {}).get("answer"), gold[r["id"]])
            by_solver.setdefault(r["solver"], []).append((r["id"], ok))
        print("\nby solver:")
        for s, items in sorted(by_solver.items()):
            oks = sum(1 for _, ok in items if ok)
            ids_s = ",".join(str(q) for q, _ in items)
            print(f"  {s:>14}: {oks}/{len(items)}  [{ids_s}]")


if __name__ == "__main__":
    main()
