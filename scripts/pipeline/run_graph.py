"""Drive the finance QA solve_qa graph over questions -> pipeline JSONL (+ scoring).

Runs arun_question() (understand -> retrieve[LIVE] -> generate_pandas ->
execute_and_repair -> verify_answer) for each requested id, converts the final
SolveState into the submission `item` shape (reusing pipeline.submission.submission_item),
and appends one record per question. The JSONL it writes is consumed directly by
scripts/pipeline/build_submission.py (it reads record["item"] / record["table_ids"]).

Usage:
  # gate: mixed labeled set (lookup + formula + multi-step), scored vs gold
  PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/run_graph.py --measure \
      --out artifacts/runs/graph_measure.jsonl

  # explicit ids
  PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/run_graph.py --ids 1,17,40 --out /tmp/r.jsonl

  # full submission run (~1012)
  PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/run_graph.py --all \
      --out artifacts/runs/graph_1012.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from finance_qa.agents.finance.graph import arun_question
from finance_qa.core.paths import QUESTION_METADATA_PATH
from finance_qa.pipelines.submission import submission_item


def load_questions() -> dict[int, dict]:
    with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
        return {int(r["id"]): r for r in map(json.loads, filter(str.strip, fh))}


def load_records(path: Path) -> list[dict]:
    """Records already written to `path`, ignoring a truncated trailing line."""
    if not path.exists():
        return []
    out = []
    for line in filter(str.strip, path.read_text(encoding="utf-8").splitlines()):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break  # a kill mid-write leaves one partial line; everything before it is good
    return out


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


async def run_one(qrow: dict) -> dict:
    """One question through the graph -> a build_submission-compatible record."""
    qid = int(qrow["id"])
    t0 = time.monotonic()
    try:
        st = await arun_question(qid, qrow["question"])
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
        "diag": st.get("diag") or {},
        "errors": st.get("errors") or [],
        # The row/column/unit trace that says *where* a wrong answer went wrong.
        # `codegen_prompt` is deliberately not recorded.
        "solution": st.get("solution") or {},
    }


def _match(pred, expected: float) -> bool:
    if pred is None:
        return False
    denom = abs(expected) if abs(expected) > 1e-9 else 1.0
    return abs(float(pred) - expected) / denom < 0.01


def preflight() -> None:
    """Die now if the endpoint will 404 every call.

    A wrong `MODEL` does not crash: each question catches the 404, records it in
    `errors`, and returns the give-up constant 0.0. So a whole run completes,
    fast, with every answer wrong. That has now happened twice (`71890ce`, and the
    85-question retry pool on 2026-08-23). One HTTP call up front is cheaper than
    finding out from the leaderboard.
    """
    import urllib.request

    from finance_qa.core.llm import ENDPOINT, MODEL

    url = ENDPOINT.replace("/chat/completions", "/models")
    try:
        with urllib.request.urlopen(url, timeout=10) as fh:
            served = [m["id"] for m in json.loads(fh.read().decode("utf-8", "replace"))["data"]]
    except Exception as exc:  # no listener, or a body we cannot parse
        sys.exit(f"preflight: cannot reach {url}: {exc}")
    if MODEL not in served:
        sys.exit(f"preflight: LLM_MODEL={MODEL!r} not served at {url}; it has {served}")
    print(f"preflight: {MODEL} live at {url}")


async def main() -> None:
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
    ap.add_argument(
        "--resume", action="store_true",
        help="append to --out, skipping ids already recorded there",
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help="questions in flight at once (async: the cap is the LLM server, not threads)",
    )
    args = ap.parse_args()
    preflight()

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
    # Without --resume the file is truncated, which is what makes an interrupted
    # 1012-question run unrecoverable: v7/v8/v9 all died mid-run and left nothing
    # to restart from.
    records = load_records(args.out) if args.resume else []
    if args.resume:
        done = {r["id"] for r in records}
        skipped, ids = len(done & set(ids)), [q for q in ids if q not in done]
        print(f"resume: {skipped} already in {args.out}, {len(ids)} left")

    print(f"running {len(ids)} question(s) through the graph -> {args.out}\n")
    print(f"{'qid':>4} {'match':>5} {'solver':>14} {'sec':>5}  {'expected':>16}  answer")
    print("-" * 92)

    def report(rec: dict) -> None:
        qid = rec["id"]
        ans = rec.get("item", {}).get("answer") if rec["status"] == "ok" else None
        exp = gold.get(qid)
        mark = "-" if exp is None else ("OK" if _match(ans, exp) else "·")
        exp_s = f"{exp:.6g}" if exp is not None else "?"
        print(f"{qid:>4} {mark:>5} {rec['solver']:>14} {rec['seconds']:>5.0f}  {exp_s:>16}  {ans}")

    # No write lock: the write/flush/report block has no await point, so a
    # coroutine cannot be preempted part-way through it.
    limit = asyncio.Semaphore(max(1, args.workers))
    with args.out.open("a" if args.resume else "w", encoding="utf-8") as fh:
        async def run_and_write(qid: int) -> dict:
            async with limit:
                rec = await run_one(questions[qid])
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            records.append(rec)
            report(rec)
            return rec

        await asyncio.gather(*(run_and_write(qid) for qid in ids))

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
    asyncio.run(main())
