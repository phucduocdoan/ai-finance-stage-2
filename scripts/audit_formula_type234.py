"""Audit formula_facts coverage for Type 2-4 shaped questions.

This report is intentionally offline: it does not call the LLM and it does not
execute new plans. It classifies each gold question by the simple fixed-scope
formula shapes we want to scale first, then compares that class against the run's
actual formula_facts gate/solver outcome.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/audit_formula_type234.py \
      artifacts/runs/gold73_after_stt_shift_fix_live.jsonl \
      --min-confidence low \
      --out artifacts/audits/formula_type234_gold73_after_stt_shift_fix_live.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from finance_qa.core.paths import QUESTION_METADATA_PATH
from finance_qa.modules.solve.common.units import MONEY_SCALE
from finance_qa.modules.solve.facts.structured_facts import metric_source_unit, metrics_in_text
from finance_qa.modules.solve.solvers.formula_facts import (
    deterministic_formula_plan,
    should_attempt_formula_facts,
)

from report_capability_failures import (  # noqa: E402
    answer_of,
    close,
    failure_bucket,
    formula_gate_reason,
    gold_tables,
    load_evalset,
    load_gold,
    load_run,
    reach_bucket,
    submitted_tables,
    used_tables,
)


_NORM_NON_WORD = re.compile(r"[^a-z0-9]+")
_SELECTION = re.compile(
    r"cao\s+nh[aấ]t|th[aấ]p\s+nh[aấ]t|l[ớo]n\s+nh[aấ]t|nh[oỏ]\s+nh[aấ]t|"
    r"nhi[eề]u\s+nh[aấ]t|[íi]t\s+nh[aấ]t|n[aă]m\s+c[oó]|c[oô]ng\s+ty\s+c[oó]|"
    r"doanh\s+nghi[ệe]p\s+c[oó]|v[aà]o\s+n[aă]m\s+.*c[oó]",
    re.I,
)
_GROWTH = re.compile(r"\btang\s+truong\b|\btoc\s+do\s+tang\b")
_DIFF = re.compile(r"\bchenh\s+lech\b|\bhieu\s+so\b|\bhon\b")
_AVG_MEDIAN = re.compile(r"\btrung\s+binh\b|\bbinh\s+quan\b|\btrung\s+vi\b")


def _norm(text: object) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NORM_NON_WORD.sub(" ", without_marks).strip()


def load_questions() -> dict[int, dict[str, Any]]:
    return {
        int(row["id"]): row
        for row in (
            json.loads(line)
            for line in QUESTION_METADATA_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def eval_level(qid: int, evalset: dict[int, dict[str, Any]]) -> str:
    value = str((evalset.get(qid) or {}).get("level") or "")
    return value.split(".", 1)[0] if value else ""


def formula_shape(qrow: dict[str, Any]) -> tuple[str, str]:
    """Classify only simple Type 2-4 formula shapes; leave the rest explicit."""
    question = str(qrow.get("question") or "")
    norm_question = _norm(question)
    tickers = [str(t).upper() for t in (qrow.get("tickers") or []) if str(t).strip()]
    years = sorted({int(y) for y in (qrow.get("years") or []) if y})
    metrics = metrics_in_text(question)
    money_metrics = [m for m in metrics if metric_source_unit(m) in MONEY_SCALE]
    ratio_metrics = [m for m in metrics if metric_source_unit(m) == "ratio"]

    if _SELECTION.search(question):
        return "selection_like", "selection marker"
    if len(tickers) == 1 and len(years) == 1 and ratio_metrics:
        return "type2_fixed_ratio", ",".join(ratio_metrics)
    if len(tickers) == 1 and len(years) == 1 and "working_capital" in metrics:
        return "type2_fixed_formula", "working_capital"
    if len(tickers) == 1 and len(years) == 2 and len(money_metrics) == 1:
        if _GROWTH.search(norm_question):
            return "type3_two_year_growth", money_metrics[0]
        if _DIFF.search(norm_question):
            return "type3_two_year_diff", money_metrics[0]
    if len(tickers) == 2 and len(years) == 1 and len(money_metrics) == 1:
        if _DIFF.search(norm_question):
            return "type4_two_ticker_diff", money_metrics[0]
    if len(tickers) == 1 and len(years) >= 2 and len(money_metrics) == 1 and _AVG_MEDIAN.search(norm_question):
        return "avg_median_candidate", money_metrics[0]
    if not metrics:
        return "no_catalog_metric", ""
    return "other_formula_or_detail", ",".join(metrics)


def run_formula_diag(rec: dict[str, Any] | None) -> dict[str, Any]:
    diag = (rec or {}).get("diag") or {}
    return diag.get("formula_facts") or {}


def build_rows(run_path: Path, *, min_confidence: str, tol: float) -> list[dict[str, Any]]:
    gold = load_gold(min_confidence)
    run = load_run(run_path)
    evalset = load_evalset()
    questions = load_questions()
    rows: list[dict[str, Any]] = []
    for qid, gold_row in sorted(gold.items()):
        rec = run.get(qid)
        qrow = questions.get(qid) or {"question": gold_row.get("question") or ""}
        shape, shape_reason = formula_shape(qrow)
        state = {
            "question": qrow.get("question") or gold_row.get("question") or "",
            "tickers": qrow.get("tickers") or [],
            "years": qrow.get("years") or [],
            "doc_type": qrow.get("doc_type") or "unknown",
            "unit_hint": qrow.get("unit_hint") or "",
            "metric": "",
        }
        gate_attempt, gate_reason = should_attempt_formula_facts(state)
        deterministic = deterministic_formula_plan(state)
        pred = answer_of(rec)
        ok = close(pred, float(gold_row["gold_answer"]), tol)
        want = gold_tables(qid, gold_row, evalset)
        reach = reach_bucket(want, used_tables(rec), submitted_tables(rec))
        formula_diag = run_formula_diag(rec)
        rows.append(
            {
                "id": qid,
                "level": eval_level(qid, evalset),
                "shape": shape,
                "shape_reason": shape_reason,
                "question": state["question"],
                "tickers": state["tickers"],
                "years": state["years"],
                "doc_type": state["doc_type"],
                "unit_hint": state["unit_hint"],
                "metrics": metrics_in_text(state["question"]),
                "formula_should_attempt": gate_attempt,
                "formula_gate_static": "" if gate_attempt else gate_reason,
                "deterministic_supported": bool(deterministic.supported),
                "deterministic_operation": deterministic.operation,
                "deterministic_metric": deterministic.answer_metric,
                "deterministic_reason": deterministic.reason,
                "run_formula_gate": formula_gate_reason(rec),
                "run_formula_done": bool(formula_diag.get("done")),
                "run_formula_reason": str(formula_diag.get("reason") or ""),
                "solver": "" if rec is None else str(rec.get("solver") or ""),
                "correct": ok,
                "answer": pred,
                "gold_answer": float(gold_row["gold_answer"]),
                "failure_bucket": failure_bucket(rec, ok, reach),
                "reach": reach,
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> None:
    print(f"rows: {len(rows)}  correct={sum(r['correct'] for r in rows)}")

    print("\nby shape:")
    by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_shape[row["shape"]].append(row)
    for shape, items in sorted(by_shape.items(), key=lambda item: (-len(item[1]), item[0])):
        ok = sum(row["correct"] for row in items)
        done = sum(row["run_formula_done"] for row in items)
        det = sum(row["deterministic_supported"] for row in items)
        miss = [row["id"] for row in items if not row["correct"]]
        print(f"  {shape:<28} ok={ok:>2}/{len(items):<2} formula_done={done:<2} det={det:<2} miss={miss}")

    target = [row for row in rows if row["shape"].startswith(("type2_", "type3_", "type4_"))]
    print(f"\nType 2-4 simple target: {sum(r['correct'] for r in target)}/{len(target)}")
    for label, key in (("run formula gate", "run_formula_gate"), ("static gate", "formula_gate_static")):
        print(f"\n{label}:")
        for value, count in Counter(str(row[key]) for row in target).most_common():
            ids = [row["id"] for row in target if str(row[key]) == value and not row["correct"]]
            print(f"  {value or 'attempt':<45} {count:>2} miss={ids}")

    print("\nmisses in Type 2-4 simple target:")
    for row in target:
        if row["correct"]:
            continue
        print(
            f"  q{row['id']} {row['shape']} solver={row['solver']} "
            f"gate={row['run_formula_gate']} det={row['deterministic_supported']} "
            f"bucket={row['failure_bucket']} metric={row['deterministic_metric'] or row['shape_reason']}\n"
            f"    {row['question']}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    ap.add_argument("--min-confidence", default="medium", choices=["high", "medium", "low"])
    ap.add_argument("--tol", type=float, default=0.01)
    ap.add_argument("--out", type=Path, help="optional JSONL detail output")
    args = ap.parse_args()

    rows = build_rows(args.run, min_confidence=args.min_confidence, tol=args.tol)
    summarize(rows)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
