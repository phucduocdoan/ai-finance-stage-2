"""Re-run generate() on all 1012 questions with frozen retrieval.

Reads table_ids from a previous pipeline run (default: full_1012.jsonl) so
retrieval is not repeated. Only generate() is re-run with the current code
(planner + REPL fallback). Output is compatible with build_submission.py.

Usage:
    PYTHONPATH=src .venv_bge/bin/python -u scripts/regen_frozen.py
    PYTHONPATH=src .venv_bge/bin/python -u scripts/regen_frozen.py --resume
    PYTHONPATH=src .venv_bge/bin/python -u scripts/regen_frozen.py \
        --source artifacts/runs/full_1012.jsonl \
        --output artifacts/runs/regen_frozen.jsonl
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from finance_qa.modules.tools.python_exec import query_names, validate
from finance_qa.modules.data.table_store import submission_csv_name
from finance_qa.core.paths import QUESTION_METADATA_PATH, RUNS_DIR
from finance_qa.modules.codegen.generator import generate

WORKERS = 4
DEFAULT_SOURCE = RUNS_DIR / "full_1012.jsonl"


def load_source(path: Path) -> dict[int, list[str]]:
    """id -> table_ids from a previous pipeline run."""
    result: dict[int, list[str]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            tids = r.get("table_ids") or []
            if tids:
                result[int(r["id"])] = tids
    return result


def load_questions(path: Path = QUESTION_METADATA_PATH) -> dict[int, dict]:
    with path.open(encoding="utf-8") as fh:
        return {int(r["id"]): r for r in map(json.loads, filter(str.strip, fh))}


def load_done(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    records: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            records[int(r["id"])] = r
    return records


def submission_item(qrow: dict, table_ids: list[str], plan: dict) -> dict:
    docs: dict[str, None] = {}
    for tid in table_ids:
        docs.setdefault(tid.rsplit("|", 1)[0], None)
    return {
        "id": int(qrow["id"]),
        "question": qrow["question"],
        "answer": plan.get("answer"),
        "relevant_docs": list(docs),
        "relevant_tables": list(table_ids),
        "evidence": plan.get("evidence", []),
        "pandas_query": plan.get("pandas_query", ""),
    }


def run_one(qrow: dict, table_ids: list[str]) -> dict:
    started = time.monotonic()
    record: dict = {
        "id": int(qrow["id"]),
        "question": qrow["question"],
        "status": "ok",
        "stage": "",
        "error": "",
        "table_ids": table_ids,
    }
    try:
        plan = generate(qrow["question"], table_ids, thinking=False, fallback=True)
    except Exception as exc:  # noqa: BLE001
        record.update(status="error", stage="plan", error=f"{type(exc).__name__}: {exc}")
        record["latency_seconds"] = round(time.monotonic() - started, 3)
        return record

    record.update(
        pandas_query=plan.get("pandas_query", ""),
        answer=plan.get("answer"),
        evidence=plan.get("evidence", []),
        planner=bool(plan.get("planner")),
        repl=bool(plan.get("repl")),
        attempts=plan.get("attempts"),
        planner_error=plan.get("error", ""),
        plan_adjustments=plan.get("plan_adjustments", []),
        plan=plan.get("plan"),
    )

    if plan.get("error") and plan.get("answer") is None:
        record.update(status="error", stage="plan", error=str(plan["error"]))
        record["latency_seconds"] = round(time.monotonic() - started, 3)
        return record

    item = submission_item(qrow, table_ids, plan)
    record["item"] = item

    try:
        errs = validate(item)
    except Exception as exc:  # noqa: BLE001
        record.update(status="error", stage="validate", error=f"{type(exc).__name__}: {exc}")
        record["latency_seconds"] = round(time.monotonic() - started, 3)
        return record

    record["validation_errors"] = errs
    if errs:
        record.update(status="invalid", stage="validate", error=errs[0])

    record["latency_seconds"] = round(time.monotonic() - started, 3)
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                    help="JSONL with frozen table_ids (default: full_1012.jsonl)")
    ap.add_argument("--output", type=Path, default=None,
                    help="output JSONL (default: artifacts/runs/regen_frozen_<ts>.jsonl)")
    ap.add_argument("--resume", action="store_true",
                    help="skip ids already written in --output")
    ap.add_argument("--retry-failed", action="store_true",
                    help="with --resume, re-run non-ok records")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--ids", help="comma-separated ids to run (default: all)")
    args = ap.parse_args(argv)

    source_tids = load_source(args.source)
    questions = load_questions()

    if args.ids:
        wanted = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
    else:
        wanted = set(source_tids.keys())

    output = args.output or (
        RUNS_DIR / f"regen_frozen_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    done = load_done(output) if args.resume else {}
    skip = {
        qid for qid, row in done.items()
        if not (args.retry_failed and row.get("status") != "ok")
    }

    pending = [
        (questions[qid], source_tids[qid])
        for qid in sorted(wanted)
        if qid in questions and qid in source_tids and qid not in skip
    ]

    print(
        f"regen_frozen: source={args.source.name} "
        f"wanted={len(wanted)} done={len(skip & wanted)} pending={len(pending)} "
        f"workers={args.workers} output={output}",
        flush=True,
    )

    if not pending:
        print("nothing to do.", flush=True)
        return 0

    started_ts = time.monotonic()
    finished = 0

    with output.open("a" if args.resume else "w", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=args.workers) as exe:
            futures = {
                exe.submit(run_one, qrow, tids): (qrow, tids)
                for qrow, tids in pending
            }
            for future in as_completed(futures):
                record = future.result()
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                finished += 1
                elapsed = time.monotonic() - started_ts
                ans = record.get("answer")
                path_tag = "planner" if record.get("planner") else ("repl" if record.get("repl") else "err")
                print(
                    f"[{finished}/{len(pending)}] id={record['id']} "
                    f"{record['status']} {path_tag} "
                    f"ans={f'{float(ans):.4g}' if ans is not None else 'None'} "
                    f"({elapsed/finished:.0f}s/q avg)",
                    flush=True,
                )
                if record["status"] != "ok":
                    print(f"    {record.get('error','')[:120]}", flush=True)

    # Summary
    all_records = list(load_done(output).values())
    n_ok = sum(1 for r in all_records if r.get("status") == "ok")
    n_planner = sum(1 for r in all_records if r.get("planner"))
    n_repl = sum(1 for r in all_records if r.get("repl"))
    n_err = sum(1 for r in all_records if r.get("status") == "error")
    print(
        f"\ndone: ok={n_ok}/{len(all_records)} "
        f"(planner={n_planner} repl={n_repl} err={n_err})",
        flush=True,
    )
    print(f"output: {output}", flush=True)
    print(
        f"next: PYTHONPATH=src .venv_bge/bin/python scripts/build_submission.py "
        f"--run {output} --out output/submission_frozen",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
