"""Run whole questions end to end: enriched question -> submission item.

The stages are the existing application APIs, called in order, with nothing
reimplemented here:

    questions_enriched.jsonl
      -> CandidateRetriever.build_pools   (hard filter + BM25 + dense + RRF + primary)
      -> CandidateRetriever.select        (LLM judge picks the evidence tables)
      -> planning.generator.generate      (symbolic plan -> pandas query -> answer)
      -> submission_item                  (the JSON shape submission_rule.txt asks for)
      -> execution.query.validate         (schema + "does the query still return answer")

Three properties this runner exists for:

**Per-stage errors, never a dead batch.** Each question records the stage it died
in and the exception text; the run continues. A judge HTTP 400 on question 300
must not cost the 700 after it.

**Resume is append-only.** Reading keeps the *last* record per id, so a retry
just appends. `--retry-failed` re-runs everything not `ok` without rewriting or
hand-editing the JSONL.

**Concurrency stays polite.** The GPU query encode is batched on the main thread
(one `build_pools` per chunk); only the LLM calls fan out, at the same 4 workers
the judge experiments used, because the vLLM endpoint is a shared service.

The planner defaults mirror `evaluation.planner` (`thinking=False`, REPL
`fallback=True`) so an end-to-end number is comparable to the ground-truth-table
benchmark instead of measuring a different planner configuration.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finance_qa.modules.tools.python_exec import validate
from finance_qa.core.paths import QUESTION_METADATA_PATH, RUNS_DIR
from finance_qa.modules.codegen.generator import generate
from finance_qa.modules.rag.candidates import CandidateRetriever
from finance_qa.modules.rag.retrievers.clients import EMBEDDING_BACKENDS, RERANKER_BACKENDS

# The judge picks at most 10 tables; passing all of them keeps multi-year
# questions whole (#363 alone needs 7 distinct tables).
MAX_TABLES = 10
WORKERS = 4  # shared vLLM endpoint -- same level the judge experiments used
CHUNK = 32  # questions per batched GPU query encode


def load_questions(path: Path = QUESTION_METADATA_PATH) -> list[dict[str, Any]]:
    """The 1,012 enriched questions, in file order."""
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def submission_item(
    question: dict[str, Any], table_ids: list[str], plan: dict[str, Any]
) -> dict[str, Any]:
    """The submission JSON for one question.

    `relevant_tables` is every table handed to the planner, not just the ones the
    query ended up reading: retrieval is scored on its own, so dropping a
    correctly retrieved table because the planner did not need it would throw
    away recall. `evidence` stays narrow -- it must match the query exactly.
    """
    docs: dict[str, None] = {}
    for table_id in table_ids:
        docs.setdefault(table_id.rsplit("|", 1)[0], None)
    return {
        "id": question["id"],
        "question": question["question"],
        "answer": plan.get("answer"),
        "relevant_docs": list(docs),
        "relevant_tables": list(table_ids),
        "evidence": plan.get("evidence", []),
        "pandas_query": plan.get("pandas_query", ""),
    }


def _failed(record: dict[str, Any], stage: str, error: str) -> dict[str, Any]:
    return {**record, "status": "error", "stage": stage, "error": error}


def _exc_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def run_question(
    retriever: CandidateRetriever,
    question: dict[str, Any],
    pool,
    *,
    max_tables: int = MAX_TABLES,
    judge_thinking: bool = True,
    plan_thinking: bool = False,
    fallback: bool = True,
    use_planner: bool = True,
) -> dict[str, Any]:
    """One question through judge -> planner -> item -> validate.

    `pool` is built by the caller so the GPU encode can be batched. Every stage
    failure is data, not an exception: the record says which stage and why.
    """
    started = time.monotonic()
    record: dict[str, Any] = {
        "id": question["id"],
        "question": question["question"],
        "status": "ok",
        "stage": "",
        "error": "",
        "query": pool.query,
        "n_candidates": len(pool.keys),
        "pool_size": len(pool.ranked),
    }

    try:
        selection = retriever.select(question, pool, thinking=judge_thinking)
    except Exception as exc:  # noqa: BLE001 - reported per stage, run continues
        return _failed(record, "retrieve", _exc_text(exc))

    picks = selection["picks"]
    # The judge returning nothing is a call failure, not a claim that no table is
    # relevant, so fall back to the retrieval order rather than to no evidence.
    table_ids = (picks or selection["ranked"])[:max_tables]
    record.update(
        picks=picks,
        table_ids=table_ids,
        judge_fallback=not picks,
        retrieve_seconds=round(time.monotonic() - started, 3),
    )
    if not table_ids:
        return _failed(record, "retrieve", "shortlist rỗng: không có candidate nào")

    plan_started = time.monotonic()
    try:
        plan = generate(
            question["question"],
            table_ids,
            thinking=plan_thinking,
            use_planner=use_planner,
            fallback=fallback,
        )
    except Exception as exc:  # noqa: BLE001 - reported per stage, run continues
        record["plan_seconds"] = round(time.monotonic() - plan_started, 3)
        return _failed(record, "plan", _exc_text(exc))

    record.update(
        plan_seconds=round(time.monotonic() - plan_started, 3),
        pandas_query=plan.get("pandas_query", ""),
        answer=plan.get("answer"),
        evidence=plan.get("evidence", []),
        planner=bool(plan.get("planner")),
        attempts=plan.get("attempts"),
        planner_error=plan.get("planner_error", ""),
        plan_adjustments=plan.get("plan_adjustments", []),
        plan=plan.get("plan"),
    )
    if plan.get("error"):
        return _failed(record, "plan", str(plan["error"]))

    item = submission_item(question, table_ids, plan)
    record["item"] = item
    try:
        errors = validate(item)
    except Exception as exc:  # noqa: BLE001 - reported per stage, run continues
        return _failed(record, "validate", _exc_text(exc))
    record["validation_errors"] = errors
    if errors:
        return {**record, "status": "invalid", "stage": "validate", "error": errors[0]}

    record["latency_seconds"] = round(time.monotonic() - started, 3)
    return record


# --------------------------------------------------------------------------- io

def read_records(path: Path) -> dict[int, dict[str, Any]]:
    """id -> its last record. Last-wins makes retries append-only."""
    records: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            records[int(row["id"])] = row
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    status = Counter(row["status"] for row in records)
    stages = Counter(row["stage"] for row in records if row["status"] != "ok")
    ok = [row for row in records if row["status"] == "ok"]
    latency = sum(float(row.get("latency_seconds") or 0.0) for row in ok)

    def rate(count: int) -> float | None:
        return round(count / total, 4) if total else None

    return {
        "total": total,
        "ok": status["ok"],
        "ok_rate": rate(status["ok"]),
        "invalid": status["invalid"],
        "error": status["error"],
        "failed_stage": dict(sorted(stages.items())),
        "judge_fallback": sum(bool(row.get("judge_fallback")) for row in records),
        "planner_answers": sum(bool(row.get("planner")) for row in ok),
        "tables_per_question": (
            round(sum(len(row.get("table_ids") or []) for row in records) / total, 2)
            if total
            else None
        ),
        "mean_latency_seconds": round(latency / len(ok), 1) if ok else None,
        "failures": [
            {
                "id": row["id"],
                "stage": row["stage"],
                "error": row["error"][:300],
            }
            for row in records
            if row["status"] != "ok"
        ],
    }


def _parse_ids(raw: str | None, available: set[int]) -> set[int]:
    if not raw:
        return available
    try:
        requested = {int(part.strip()) for part in raw.split(",") if part.strip()}
    except ValueError as exc:
        raise ValueError("--ids must be comma-separated integers") from exc
    unknown = sorted(requested - available)
    if unknown:
        raise ValueError(f"unknown question ids: {unknown}")
    return requested


def _default_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return RUNS_DIR / f"pipeline_{stamp}.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run questions end to end and write submission items."
    )
    parser.add_argument("--ids", help="comma-separated question ids; default: all")
    parser.add_argument("--limit", type=int, help="only the first N selected questions")
    parser.add_argument("--output", type=Path, help="JSONL result path")
    parser.add_argument(
        "--resume", action="store_true", help="skip ids already in --output"
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="with --resume, re-run ids whose last record is not ok",
    )
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--chunk", type=int, default=CHUNK)
    parser.add_argument("--max-tables", type=int, default=MAX_TABLES)
    parser.add_argument(
        "--no-judge-thinking",
        action="store_true",
        help="judge without thinking (much faster, measured worse)",
    )
    parser.add_argument(
        "--thinking", action="store_true", help="enable thinking for the planner"
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="skip the REPL fallback and report the planner failure directly",
    )
    parser.add_argument(
        "--no-planner",
        action="store_true",
        help="skip planner DSL entirely, go straight to REPL for every question",
    )
    parser.add_argument(
        "--dense-backend",
        default="bge-m3",
        choices=list(EMBEDDING_BACKENDS),
        help="dense channel encoder; qwen3-4b needs its DeepInfra index built",
    )
    parser.add_argument(
        "--reranker",
        default=None,
        choices=list(RERANKER_BACKENDS),
        help="reorder the fused pool with a cross-encoder (default: off)",
    )
    parser.add_argument(
        "--judge-top-n",
        type=int,
        default=None,
        help="show the judge only the top N of the pool (default: the whole pool)",
    )
    parser.add_argument(
        "--list", action="store_true", help="print the selection without calling anything"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    questions = load_questions()
    selected_ids = _parse_ids(args.ids, {int(q["id"]) for q in questions})
    selected = [q for q in questions if int(q["id"]) in selected_ids]
    if args.limit:
        selected = selected[: args.limit]
        selected_ids = {int(q["id"]) for q in selected}

    if args.list:
        for question in selected:
            print(
                f"{question['id']:>4} tickers={question.get('tickers')} "
                f"years={question.get('years')} doc_type={question.get('doc_type')}"
            )
        print(f"{len(selected)} questions")
        return 0

    output = (args.output or _default_output()).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.resume:
        raise FileExistsError(f"output already exists; pass --resume: {output}")

    done = read_records(output) if args.resume else {}
    skip = {
        qid
        for qid, row in done.items()
        if not (args.retry_failed and row.get("status") != "ok")
    }
    pending = [q for q in selected if int(q["id"]) not in skip]
    print(
        f"pipeline: selected={len(selected)} done={len(skip & selected_ids)} "
        f"pending={len(pending)} workers={args.workers} output={output}",
        flush=True,
    )

    if pending:
        retriever = CandidateRetriever(
            expand_primary=True,
            strip_query=True,
            load_judge_text=True,
            dense_backend=args.dense_backend,
            reranker=args.reranker,
            judge_top_n=args.judge_top_n,
        )
        started = time.monotonic()
        finished = 0
        with output.open("a" if args.resume else "x", encoding="utf-8") as fh:
            for offset in range(0, len(pending), args.chunk):
                chunk = pending[offset : offset + args.chunk]
                try:
                    pools = retriever.build_pools(chunk)
                except Exception as exc:  # noqa: BLE001 - one bad chunk, not the run
                    text = _exc_text(exc)
                    print(f"  chunk at {offset} failed to build pools: {text}", flush=True)
                    for question in chunk:
                        fh.write(
                            json.dumps(
                                _failed(
                                    {
                                        "id": question["id"],
                                        "question": question["question"],
                                        "status": "ok",
                                        "stage": "",
                                        "error": "",
                                    },
                                    "retrieve",
                                    text,
                                ),
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                    fh.flush()
                    finished += len(chunk)
                    continue

                with ThreadPoolExecutor(max_workers=args.workers) as pool_executor:
                    futures = {
                        pool_executor.submit(
                            run_question,
                            retriever,
                            question,
                            candidate_pool,
                            max_tables=args.max_tables,
                            judge_thinking=not args.no_judge_thinking,
                            plan_thinking=args.thinking,
                            fallback=not args.no_fallback,
                            use_planner=not args.no_planner,
                        ): question
                        for question, candidate_pool in zip(chunk, pools)
                    }
                    for future in as_completed(futures):
                        record = future.result()
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                        fh.flush()
                        finished += 1
                        elapsed = time.monotonic() - started
                        print(
                            f"[{finished}/{len(pending)}] id={record['id']} "
                            f"{record['status']}{'/' + record['stage'] if record['stage'] else ''} "
                            f"answer={record.get('answer')} "
                            f"({elapsed / finished:.0f}s/q avg)",
                            flush=True,
                        )
                        if record["status"] != "ok":
                            print(f"    {record['error'][:200]}", flush=True)

    records = [
        row for qid, row in sorted(read_records(output).items()) if qid in selected_ids
    ]
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results_path": str(output),
        "n_selected": len(selected_ids),
        "max_tables": args.max_tables,
        "judge_thinking": not args.no_judge_thinking,
        "planner_thinking": bool(args.thinking),
        "fallback": not args.no_fallback,
        "use_planner": not args.no_planner,
        "dense_backend": args.dense_backend,
        "reranker": args.reranker,
        "judge_top_n": args.judge_top_n,
        **summarize(records),
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"done: ok={summary['ok']}/{summary['total']} invalid={summary['invalid']} "
        f"error={summary['error']} summary={summary_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
