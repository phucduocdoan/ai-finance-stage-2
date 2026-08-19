"""Evaluate the structured fact planner against hand-labeled semantic plans.

This is an offline development harness for ``modules.solve.facts.structured_facts``.
It measures whether the LLM fills the bounded Pydantic plan correctly; it does
not run retrieval or pandas codegen.

Examples:
  PYTHONPATH=src .venv_bge/bin/python scripts/eval_structured_planner.py --offline --execute
  PYTHONPATH=src .venv_bge/bin/python scripts/eval_structured_planner.py \
      --ids 363,381,390 --out artifacts/runs/structured_planner_eval.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401

from finance_qa.core.paths import QUESTION_METADATA_PATH
from finance_qa.modules.solve.facts.structured_facts import (
    StructuredFactError,
    StructuredPlan,
    aplan_structured,
    execute_plan,
    normalize_plan,
    supported_v1_plan,
)


DEFAULT_LABELS = Path("data/eval/structured_plan_gold.jsonl")
CORE_COMPARE_FIELDS = [
    "supported",
    "operation",
    "axis",
    "tickers",
    "years",
    "doc_type",
    "selector_metric",
    "selector_order",
    "answer_metric",
    "answer_expression",
    "filters",
    "year_offset",
    "missing_policy",
    "target_unit",
]
ADVISORY_FIELDS = [
    "scenario_factor",
    "round_digits",
]
COMPARE_FIELDS = CORE_COMPARE_FIELDS + ADVISORY_FIELDS


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_questions() -> dict[int, dict[str, Any]]:
    return {int(row["id"]): row for row in load_jsonl(QUESTION_METADATA_PATH)}


def parse_ids(raw: str) -> set[int] | None:
    if not raw:
        return None
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


def expected_plan(label: dict[str, Any]) -> StructuredPlan:
    return normalize_plan(StructuredPlan.model_validate(label["expected"]))


def filter_key(row: dict[str, Any]) -> tuple[Any, ...]:
    value = row.get("value")
    if value is not None:
        value = round(float(value), 12)
    return (
        row.get("metric") or "",
        row.get("relation") or "",
        value,
        row.get("value_source") or "literal",
    )


def comparable(plan: StructuredPlan) -> dict[str, Any]:
    raw = normalize_plan(plan.model_copy(deep=True)).model_dump()
    raw["tickers"] = [str(t).upper().strip() for t in raw.get("tickers") or []]
    raw["years"] = sorted(int(y) for y in raw.get("years") or [])
    raw["filters"] = sorted(
        filter_key(row)
        for row in raw.get("filters") or []
        if row.get("metric")
    )
    if raw.get("scenario_factor") is not None:
        raw["scenario_factor"] = round(float(raw["scenario_factor"]), 12)
    return {field: raw.get(field) for field in COMPARE_FIELDS}


def field_matches(expected: StructuredPlan, predicted: StructuredPlan) -> dict[str, bool]:
    exp = comparable(expected)
    pred = comparable(predicted)
    return {field: exp[field] == pred[field] for field in COMPARE_FIELDS}


def answer_error(got: float | None, expected: float | None) -> float | None:
    if got is None or expected is None:
        return None
    if not math.isfinite(got) or not math.isfinite(expected):
        return None
    return abs(got - expected) / max(abs(expected), 1.0)


def load_gold_answers() -> dict[int, float]:
    paths = [
        Path("data/eval/extended_gold.jsonl"),
        Path("data/eval/unbiased60_gold.jsonl"),
        Path("data/eval/manual15_gold.jsonl"),
    ]
    answers: dict[int, float] = {}
    for path in paths:
        if not path.exists():
            continue
        for row in load_jsonl(path):
            value = row.get("gold_answer", row.get("answer"))
            if value is None:
                continue
            try:
                answers[int(row["id"])] = float(value)
            except (TypeError, ValueError):
                continue
    return answers


async def evaluate_label(
    label: dict[str, Any],
    question: dict[str, Any],
    gold_answers: dict[int, float],
    *,
    offline: bool,
    thinking: bool,
    execute: bool,
) -> dict[str, Any]:
    qid = int(label["id"])
    expected = expected_plan(label)
    if offline:
        predicted = expected.model_copy(deep=True)
    else:
        predicted = await aplan_structured(
            question=str(question["question"]),
            tickers=list(expected.tickers),
            years=list(expected.years),
            doc_type=expected.doc_type,
            metric=str(label.get("input_metric") or ""),
            operation=str(label.get("input_operation") or ""),
            unit_hint=str(question.get("unit_hint") or ""),
            planner_thinking=thinking,
        )

    matches = field_matches(expected, predicted)
    v1_ok, v1_reason = supported_v1_plan(
        predicted,
        str(question["question"]),
        str(question.get("unit_hint") or ""),
    )
    record: dict[str, Any] = {
        "id": qid,
        "score": bool(label.get("score", True)),
        "type": label.get("type", ""),
        "question": question["question"],
        "exact": all(matches[field] for field in CORE_COMPARE_FIELDS),
        "wrong_fields": [field for field in CORE_COMPARE_FIELDS if not matches[field]],
        "advisory_wrong_fields": [
            field for field in ADVISORY_FIELDS if not matches[field]
        ],
        "fields": matches,
        "supported_v1": {"ok": v1_ok, "reason": v1_reason},
        "expected": comparable(expected),
        "predicted": comparable(predicted),
        "predicted_raw": predicted.model_dump(),
    }

    if execute:
        try:
            out = execute_plan(
                predicted,
                question=str(question["question"]),
                unit_hint=str(question.get("unit_hint") or ""),
            )
            got = float(out["answer"])
            gold = gold_answers.get(qid)
            record["execution"] = {
                "ok": True,
                "answer": got,
                "gold_answer": gold,
                "relative_error": answer_error(got, gold),
                "selected": out.get("diag", {}).get("selected", {}),
            }
        except (StructuredFactError, Exception) as exc:
            record["execution"] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    return record


def print_summary(records: list[dict[str, Any]]) -> None:
    scored = [row for row in records if row["score"]]
    exact = sum(1 for row in scored if row["exact"])
    print(f"labels: {len(scored)} scored / {len(records)} total")
    if scored:
        print(f"exact:  {exact}/{len(scored)} ({exact / len(scored):.1%})")
    print("\ncore field accuracy")
    for field in CORE_COMPARE_FIELDS:
        hits = sum(1 for row in scored if row["fields"].get(field))
        denom = len(scored) or 1
        print(f"  {field:<18} {hits:>3}/{len(scored):<3} ({hits / denom:.1%})")

    print("\nadvisory field accuracy")
    for field in ADVISORY_FIELDS:
        hits = sum(1 for row in scored if row["fields"].get(field))
        denom = len(scored) or 1
        print(f"  {field:<18} {hits:>3}/{len(scored):<3} ({hits / denom:.1%})")

    misses = [row for row in scored if not row["exact"]]
    if misses:
        print("\nmisses")
        for row in misses:
            print(f"  q{row['id']}: {', '.join(row['wrong_fields'])}")

    exec_rows = [row for row in records if "execution" in row]
    if exec_rows:
        ok = sum(1 for row in exec_rows if row["execution"].get("ok"))
        close = sum(
            1
            for row in exec_rows
            if row["execution"].get("relative_error") is not None
            and row["execution"]["relative_error"] <= 0.01
        )
        print(f"\nexecution: ok={ok}/{len(exec_rows)}  gold-close={close}/{len(exec_rows)}")

    by_wrong_field = Counter(
        field
        for row in scored
        for field in row["wrong_fields"]
    )
    if by_wrong_field:
        print("\nwrong field counts")
        for field, count in by_wrong_field.most_common():
            print(f"  {field:<18} {count}")


async def amain(args: argparse.Namespace) -> int:
    labels = load_jsonl(args.labels)
    ids = parse_ids(args.ids)
    if ids is not None:
        labels = [row for row in labels if int(row["id"]) in ids]
    if not args.include_review:
        labels = [row for row in labels if row.get("score", True)]
    if not labels:
        raise SystemExit("no labels selected")

    questions = load_questions()
    gold_answers = load_gold_answers()
    missing = [int(row["id"]) for row in labels if int(row["id"]) not in questions]
    if missing:
        raise SystemExit(f"missing question metadata for ids: {missing}")

    sem = asyncio.Semaphore(args.concurrency)

    async def run_one(label: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            qid = int(label["id"])
            return await evaluate_label(
                label,
                questions[qid],
                gold_answers,
                offline=args.offline,
                thinking=args.thinking,
                execute=args.execute,
            )

    records = await asyncio.gather(*(run_one(label) for label in labels))
    records.sort(key=lambda row: int(row["id"]))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for row in records:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {args.out}")

    print_summary(records)
    return 0 if all(row["exact"] or not row["score"] for row in records) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--ids", default="", help="Comma-separated question ids")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--offline", action="store_true", help="validate labels without LLM calls")
    parser.add_argument("--thinking", action="store_true", help="enable planner thinking")
    parser.add_argument("--execute", action="store_true", help="execute predicted plans and compare to gold answers")
    parser.add_argument("--include-review", action="store_true", help="include labels marked score=false")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    args.concurrency = max(1, int(args.concurrency))
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
