"""Benchmark query planning against curated answers and ground-truth tables."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finance_qa.paths import EVALSET_PATH, EVAL_DIR, RUNS_DIR
from finance_qa.planning.generator import generate

ANSWERS_PATH = EVAL_DIR / "planner_answers.json"


def load_cases(
    evalset_path: Path = EVALSET_PATH,
    answers_path: Path = ANSWERS_PATH,
) -> list[dict[str, Any]]:
    """Join curated numeric answers to eval questions with table-level labels."""
    evalset = json.loads(evalset_path.read_text(encoding="utf-8"))
    labels = json.loads(answers_path.read_text(encoding="utf-8"))
    by_qid = {int(row["qid"]): row for row in evalset if row.get("gt_tables")}
    label_by_qid = {int(row["qid"]): row for row in labels}

    if len(label_by_qid) != len(labels):
        raise ValueError(f"duplicate qid in {answers_path}")
    missing = sorted(set(by_qid) - set(label_by_qid))
    extra = sorted(set(label_by_qid) - set(by_qid))
    if missing or extra:
        raise ValueError(
            f"planner answer coverage mismatch: missing={missing}, extra={extra}"
        )

    cases = []
    for qid in sorted(by_qid):
        case = dict(by_qid[qid])
        case["label"] = label_by_qid[qid]
        # A gt_tables entry is an equivalence group. Use its first verified table;
        # separate groups are all required by the question.
        case["table_ids"] = [group[0] for group in case["gt_tables"]]
        cases.append(case)
    return cases


def score_answer(predicted: Any, label: dict[str, Any]) -> dict[str, Any]:
    """Score one numeric answer with the tolerance recorded in eval data."""
    expected = float(label["expected"])
    try:
        value = float(predicted)
    except (TypeError, ValueError):
        return {
            "predicted": None,
            "expected": expected,
            "abs_error": None,
            "relative_error": None,
            "correct": False,
        }
    if not math.isfinite(value):
        return {
            "predicted": value,
            "expected": expected,
            "abs_error": None,
            "relative_error": None,
            "correct": False,
        }

    abs_error = abs(value - expected)
    relative_error = abs_error / abs(expected) if expected else abs_error
    return {
        "predicted": value,
        "expected": expected,
        "abs_error": abs_error,
        "relative_error": relative_error,
        "correct": math.isclose(
            value,
            expected,
            rel_tol=float(label["rel_tolerance"]),
            abs_tol=float(label["abs_tolerance"]),
        ),
    }


def evaluate_case(
    case: dict[str, Any],
    *,
    thinking: bool = False,
    fallback: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    result = generate(
        case["question"],
        case["table_ids"],
        thinking=thinking,
        fallback=fallback,
    )
    latency = time.monotonic() - started
    executable = not bool(result.get("error"))
    score = score_answer(result.get("answer"), case["label"])
    if not executable:
        score["correct"] = False

    planner = bool(result.get("planner"))
    if not executable:
        status = "generation_error"
    elif score["correct"] and planner:
        status = "correct_planner"
    elif score["correct"]:
        status = "correct_fallback"
    elif planner:
        status = "wrong_planner_answer"
    else:
        status = "wrong_fallback_answer"

    return {
        "qid": case["qid"],
        "level": case["level"],
        "question": case["question"],
        "table_ids": case["table_ids"],
        "unit": case["label"]["unit"],
        "label_source": case["label"]["source"],
        "abs_tolerance": case["label"]["abs_tolerance"],
        "rel_tolerance": case["label"]["rel_tolerance"],
        **score,
        "status": status,
        "executable": executable,
        "planner": planner,
        "planner_success": executable and planner,
        "fallback_success": executable and not planner,
        "latency_seconds": round(latency, 3),
        "pandas_query": result.get("pandas_query", ""),
        "error": result.get("error", ""),
        "attempts": result.get("attempts"),
        "planner_error": result.get("planner_error", ""),
        "planner_attempts": result.get("planner_attempts", result.get("attempts")),
        "plan": result.get("plan"),
        "failed_plan": result.get("failed_plan"),
        "plan_adjustments": result.get("plan_adjustments", []),
        "evidence": result.get("evidence", []),
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    executable = sum(bool(row["executable"]) for row in records)
    correct = sum(bool(row["correct"]) for row in records)
    planner_outputs = sum(bool(row["planner_success"]) for row in records)
    planner_correct = sum(
        bool(row["planner_success"] and row["correct"]) for row in records
    )
    fallback_outputs = sum(bool(row["fallback_success"]) for row in records)
    fallback_correct = sum(
        bool(row["fallback_success"] and row["correct"]) for row in records
    )
    latency = sum(float(row["latency_seconds"]) for row in records)

    def rate(numerator: int, denominator: int = total) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "total": total,
        "executable": executable,
        "executable_rate": rate(executable),
        "correct": correct,
        "accuracy": rate(correct),
        "planner_outputs": planner_outputs,
        "planner_coverage": rate(planner_outputs),
        "planner_correct": planner_correct,
        "planner_precision": rate(planner_correct, planner_outputs),
        "fallback_outputs": fallback_outputs,
        "fallback_correct": fallback_correct,
        "fallback_precision": rate(fallback_correct, fallback_outputs),
        "latency_seconds": round(latency, 3),
        "mean_latency_seconds": round(latency / total, 3) if total else None,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_level[row["level"]].append(row)
    return {
        "overall": _aggregate(records),
        "by_level": {
            level: _aggregate(rows) for level, rows in sorted(by_level.items())
        },
        "failures": [
            {
                "qid": row["qid"],
                "level": row["level"],
                "status": row["status"],
                "predicted": row["predicted"],
                "expected": row["expected"],
                "error": row["error"],
                "planner_error": row["planner_error"],
            }
            for row in records
            if not row["correct"]
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
        raise ValueError(f"qids do not have planner labels: {unknown}")
    return requested


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
    return records


def _default_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return RUNS_DIR / f"planner_eval_{stamp}.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate planner/query quality using ground-truth tables."
    )
    parser.add_argument("--ids", help="comma-separated qids; default: all 15")
    parser.add_argument("--output", type=Path, help="JSONL result path")
    parser.add_argument(
        "--resume", action="store_true", help="skip qids already in --output"
    )
    parser.add_argument(
        "--thinking", action="store_true", help="enable thinking for every LLM call"
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="skip the REPL fallback and report the planner failure directly",
    )
    parser.add_argument(
        "--list", action="store_true", help="print selected cases without calling the LLM"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = load_cases()
    selected_ids = _parse_ids(args.ids, {int(case["qid"]) for case in cases})
    cases = [case for case in cases if int(case["qid"]) in selected_ids]

    if args.list:
        for case in cases:
            print(
                f"{case['qid']:>3} {case['level']:<4} "
                f"tables={len(case['table_ids'])} expected={case['label']['expected']}"
            )
        return 0

    output = (args.output or _default_output()).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.resume:
        raise FileExistsError(f"output already exists; pass --resume: {output}")

    existing = _read_jsonl(output) if args.resume else []
    completed = {int(row["qid"]) for row in existing}
    pending = [case for case in cases if int(case["qid"]) not in completed]
    mode = "a" if args.resume else "x"
    print(
        f"planner benchmark: selected={len(cases)} completed={len(completed & selected_ids)} "
        f"pending={len(pending)} output={output}",
        flush=True,
    )

    with output.open(mode, encoding="utf-8") as fh:
        for index, case in enumerate(pending, 1):
            print(
                f"[{index}/{len(pending)}] qid={case['qid']} level={case['level']}...",
                flush=True,
            )
            record = evaluate_case(
                case,
                thinking=args.thinking,
                fallback=not args.no_fallback,
            )
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            print(
                f"  {record['status']} predicted={record['predicted']} "
                f"expected={record['expected']} latency={record['latency_seconds']:.1f}s",
                flush=True,
            )

    records = [
        row
        for row in _read_jsonl(output)
        if int(row["qid"]) in selected_ids
    ]
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results_path": str(output),
        "selected_qids": sorted(selected_ids),
        "fallback": not args.no_fallback,
        "thinking": bool(args.thinking),
        **summarize(records),
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    overall = summary["overall"]
    print(
        f"done: correct={overall['correct']}/{overall['total']} "
        f"planner={overall['planner_correct']}/{overall['planner_outputs']} "
        f"summary={summary_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
