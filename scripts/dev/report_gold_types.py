"""Score a run and break misses down by question type and evidence reach.

This is a development report, not part of the submitted pipeline. It uses the
hand-labeled gold files plus `data/eval/evalset.json` when a manual L1-L6 label
exists; otherwise it falls back to the metadata/proxy shape already produced by
the pipeline.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/report_gold_types.py artifacts/runs/run.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from finance_qa.core.paths import QUESTION_METADATA_PATH

GOLD_FILES = (
    Path("data/eval/unbiased60_gold.jsonl"),
    Path("data/eval/manual15_gold.jsonl"),
)
EVALSET = Path("data/eval/evalset.json")
TOL = 0.01


def load_gold() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for path in GOLD_FILES:
        for line in filter(str.strip, path.read_text(encoding="utf-8").splitlines()):
            row = json.loads(line)
            if str(row.get("confidence", "")).lower() in {"low", "none", ""}:
                continue
            if row.get("gold_answer") is None:
                continue
            out[int(row["id"])] = row
    return out


def load_levels() -> dict[int, str]:
    if not EVALSET.exists():
        return {}
    rows = json.loads(EVALSET.read_text(encoding="utf-8"))
    return {int(row["qid"]): str(row["level"]).split(".", 1)[0] for row in rows}


def load_questions() -> dict[int, dict]:
    with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
        return {int(row["id"]): row for row in map(json.loads, filter(str.strip, fh))}


def load_run(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for line in filter(str.strip, path.read_text(encoding="utf-8").splitlines()):
        rec = json.loads(line)
        out[int(rec.get("id") or rec.get("item", {}).get("id"))] = rec
    return out


def answer_of(rec: dict) -> float | None:
    value = (rec.get("item") or {}).get("answer", rec.get("answer"))
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def is_year_answer(row: dict) -> bool:
    unit = str(row.get("gold_unit") or row.get("unit_asked") or "").strip().lower()
    return unit in {"năm", "nam", "year", "years"}


def close(pred: float | None, gold: float, *, year_answer: bool = False) -> bool:
    if pred is None:
        return False
    if year_answer:
        return abs(pred - gold) <= 1e-6
    if gold == 0:
        return abs(pred) <= TOL
    return abs(pred - gold) / abs(gold) <= TOL


def proxy_level(qrow: dict) -> str:
    if qrow.get("answer_shape") == "single_cell" or qrow.get("operation") == "lookup":
        return "P1"
    if qrow.get("operation") == "formula":
        return "P2"
    if qrow.get("multi_year"):
        return "P5"
    if qrow.get("multi_company"):
        return "P4"
    return "P6"


def gold_tables(row: dict) -> set[str]:
    return {
        chunk.split("(", 1)[0].strip()
        for text in str(row.get("evidence_table_id") or "").split(";")
        for chunk in text.split(",")
        if "|" in chunk
    }


def miss_bucket(rec: dict, gold_row: dict) -> str:
    want = gold_tables(gold_row)
    if not want:
        return "wrong_no_gold_table_label"
    prompted = set((rec.get("diag") or {}).get("evidence_tables") or [])
    submitted = set(rec.get("table_ids") or rec.get("relevant_tables") or [])
    if want & prompted:
        return "wrong_gold_prompted"
    if want & submitted:
        return "wrong_gold_retrieved_not_prompted"
    return "wrong_no_gold_retrieved"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    args = ap.parse_args()

    gold = load_gold()
    levels = load_levels()
    questions = load_questions()
    run = load_run(args.run)

    by_level: dict[str, list[tuple[int, bool, str]]] = {}
    by_solver: dict[str, list[tuple[int, bool]]] = {}
    for qid, row in gold.items():
        rec = run.get(qid)
        if rec is None:
            ok, bucket, solver = False, "missing_from_run", "missing"
        else:
            ok = close(answer_of(rec), float(row["gold_answer"]), year_answer=is_year_answer(row))
            bucket = "correct" if ok else miss_bucket(rec, row)
            solver = str(rec.get("solver") or "?")
        level = levels.get(qid) or proxy_level(questions.get(qid, {}))
        by_level.setdefault(level, []).append((qid, ok, bucket))
        by_solver.setdefault(solver, []).append((qid, ok))

    total_ok = sum(ok for rows in by_level.values() for _, ok, _ in rows)
    total = sum(len(rows) for rows in by_level.values())
    print(f"{args.run}: {total_ok}/{total} ({total_ok / total:.1%})")

    print("\nby level:")
    for level, rows in sorted(by_level.items()):
        ok = sum(1 for _, hit, _ in rows if hit)
        print(f"  {level:>3}: {ok:>2}/{len(rows):<2} ({ok / len(rows):5.1%})")
        buckets: dict[str, list[int]] = {}
        for qid, hit, bucket in rows:
            if not hit:
                buckets.setdefault(bucket, []).append(qid)
        for bucket, ids in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
            print(f"       {bucket}: {ids}")

    print("\nby solver:")
    for solver, rows in sorted(by_solver.items()):
        ok = sum(1 for _, hit in rows if hit)
        print(f"  {solver:>16}: {ok:>2}/{len(rows):<2} ({ok / len(rows):5.1%})")


if __name__ == "__main__":
    main()
