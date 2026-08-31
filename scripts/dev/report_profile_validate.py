"""Audit TableProfile validation findings on an existing run JSONL.

This is offline and deterministic: it reloads only the CSVs already listed in
each record's evidence, reruns ``validate_profile_selection`` against the final
query, and reports whether findings concentrate on wrong answers.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/report_profile_validate.py \
      artifacts/runs/gold73_after_stt_shift_fix_live.jsonl \
      --out artifacts/audits/profile_validate_gold73_after_stt_shift_fix_live.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.facts.profile_validate import validate_profile_selection

from report_capability_failures import (  # noqa: E402
    answer_of,
    close,
    load_evalset,
    load_gold,
    load_run,
)


_CSV_TABLE_PATH = re.compile(r"^(.+?)_table_(\d+)\.csv$")


def _table_id_from_csv(csv_path: str) -> str:
    match = _CSV_TABLE_PATH.search(Path(csv_path).name)
    if not match:
        return ""
    return f"{match.group(1)}|{int(match.group(2))}"


def _evidence_bindings(rec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    frames: dict[str, Any] = {}
    names: dict[str, str] = {}
    errors: list[str] = []
    for ev in (rec.get("item") or {}).get("evidence") or rec.get("evidence") or []:
        variable = str(ev.get("variable") or "")
        table_id = _table_id_from_csv(str(ev.get("csv_path") or ""))
        if not variable or not table_id:
            continue
        names[variable] = table_id
        try:
            frames[variable] = load_frame(table_id)
        except Exception as exc:  # noqa: BLE001 - audit should continue
            errors.append(f"{variable}:{table_id}:{type(exc).__name__}:{exc}")
    return frames, names, errors


def _state_from_record(rec: dict[str, Any]) -> dict[str, Any]:
    item = rec.get("item") or {}
    return {
        "id": rec.get("id") or item.get("id"),
        "question": rec.get("question") or item.get("question") or "",
        "answer": answer_of(rec),
        "pandas_query": item.get("pandas_query") or rec.get("pandas_query") or "",
        "solution": rec.get("solution") or {},
        "diag": rec.get("diag") or {},
        "solver": rec.get("solver") or "",
    }


def _codes(findings: Iterable[dict[str, Any]], severity: str | None = None) -> list[str]:
    out: list[str] = []
    for finding in findings:
        if severity is not None and finding.get("severity") != severity:
            continue
        out.append(str(finding.get("code") or ""))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    ap.add_argument("--out", type=Path, help="optional JSONL findings output")
    ap.add_argument("--min-confidence", default="high", choices=["high", "medium", "low"])
    args = ap.parse_args()

    gold = load_gold(args.min_confidence)
    evalset = load_evalset()
    records = load_run(args.run)

    rows: list[dict[str, Any]] = []
    correct = wrong = 0
    any_flag = Counter()
    strong_flag = Counter()
    weak_flag = Counter()
    codes_by_outcome: dict[str, Counter] = {"correct": Counter(), "wrong": Counter()}
    strong_codes_by_outcome: dict[str, Counter] = {"correct": Counter(), "wrong": Counter()}

    for qid, gold_row in sorted(gold.items()):
        rec = records.get(qid)
        if rec is None:
            continue
        pred = answer_of(rec)
        is_correct = close(pred, float(gold_row["gold_answer"]))
        outcome = "correct" if is_correct else "wrong"
        correct += int(is_correct)
        wrong += int(not is_correct)

        frames, names, load_errors = _evidence_bindings(rec)
        diag = validate_profile_selection(_state_from_record(rec), frames, names)
        findings = list(diag.get("findings") or [])
        codes = _codes(findings)
        strong_codes = _codes(findings, "strong")
        weak_codes = _codes(findings, "weak")

        any_flag[outcome] += int(bool(codes))
        strong_flag[outcome] += int(bool(strong_codes))
        weak_flag[outcome] += int(bool(weak_codes))
        codes_by_outcome[outcome].update(codes)
        strong_codes_by_outcome[outcome].update(strong_codes)
        rows.append(
            {
                "id": qid,
                "level": str((evalset.get(qid) or {}).get("level") or ""),
                "correct": is_correct,
                "solver": rec.get("solver") or "",
                "answer": pred,
                "gold_answer": float(gold_row["gold_answer"]),
                "codes": codes,
                "strong_codes": strong_codes,
                "weak_codes": weak_codes,
                "summary": diag.get("summary") or {},
                "query_cells": diag.get("query_cells") or [],
                "findings": findings,
                "load_errors": load_errors,
            }
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"run: {args.run}")
    print(f"scored: {correct + wrong}  correct={correct}  wrong={wrong}")
    print(f"any finding: correct={any_flag['correct']}  wrong={any_flag['wrong']}")
    print(f"strong finding: correct={strong_flag['correct']}  wrong={strong_flag['wrong']}")
    print(f"weak finding: correct={weak_flag['correct']}  wrong={weak_flag['wrong']}")
    print("\nstrong codes on wrong answers:")
    for code, count in strong_codes_by_outcome["wrong"].most_common():
        print(f"  {code}: {count}")
    print("\nstrong codes on correct answers:")
    for code, count in strong_codes_by_outcome["correct"].most_common():
        print(f"  {code}: {count}")
    print("\nall codes on wrong answers:")
    for code, count in codes_by_outcome["wrong"].most_common():
        print(f"  {code}: {count}")


if __name__ == "__main__":
    main()
