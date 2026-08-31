"""Audit a run by solver capability, gold-table reach, and miss bucket.

This is a reporting tool only. It does not call the LLM and does not change the
answer graph. The goal is to separate failures that need better table/cell
understanding from failures that need retrieval, evidence-budget, or new fact
layers.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/report_capability_failures.py \
      artifacts/runs/formula_facts_gold73_after_type4_entity_diff.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from finance_qa.core.paths import EVALSET_PATH, QUESTION_METADATA_PATH


GOLD_FILES = (
    Path("data/eval/unbiased60_gold.jsonl"),
    Path("data/eval/manual15_gold.jsonl"),
)
CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1, "unresolvable": 0, "": 0}
DEFAULT_TOL = 0.01

_FULL_TABLE_ID = re.compile(r"([A-Z0-9]+_financial_statements_[^|,;&\s()]+)\|(\d+)")
_BARE_TABLE_POS = re.compile(r"^\|?(\d+)$")
_CSV_TABLE_PATH = re.compile(r"^(.+?)_table_(\d+)\.csv$")


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def load_gold(min_confidence: str) -> dict[int, dict[str, Any]]:
    floor = CONFIDENCE_ORDER[min_confidence]
    out: dict[int, dict[str, Any]] = {}
    for path in GOLD_FILES:
        for row in iter_jsonl(path):
            confidence = str(row.get("confidence") or "").lower()
            if CONFIDENCE_ORDER.get(confidence, 0) < floor:
                continue
            if row.get("gold_answer") is None:
                continue
            out[int(row["id"])] = row
    return out


def load_run(path: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for rec in iter_jsonl(path):
        qid = rec.get("id") or (rec.get("item") or {}).get("id")
        if qid is not None:
            out[int(qid)] = rec
    return out


def load_evalset() -> dict[int, dict[str, Any]]:
    if not EVALSET_PATH.exists():
        return {}
    return {int(row["qid"]): row for row in json.loads(EVALSET_PATH.read_text(encoding="utf-8"))}


def load_questions() -> dict[int, dict[str, Any]]:
    if not QUESTION_METADATA_PATH.exists():
        return {}
    return {int(row["id"]): row for row in iter_jsonl(QUESTION_METADATA_PATH)}


def answer_of(rec: dict[str, Any] | None) -> float | None:
    if rec is None:
        return None
    value = (rec.get("item") or {}).get("answer", rec.get("answer"))
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def is_year_answer(row: dict[str, Any]) -> bool:
    unit = str(row.get("gold_unit") or row.get("unit_asked") or "").strip().lower()
    return unit in {"năm", "nam", "year", "years"}


def close(
    pred: float | None,
    gold: float,
    tol: float = DEFAULT_TOL,
    *,
    year_answer: bool = False,
) -> bool:
    if pred is None:
        return False
    if year_answer:
        return abs(pred - gold) <= 1e-6
    if gold == 0.0:
        return abs(pred) <= tol
    return abs(pred - gold) <= tol * abs(gold)


def flatten(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list[Any] = []
        for item in value:
            out.extend(flatten(item))
        return out
    return [value]


def _normalize_table_id(report_id: str, pos: str) -> str:
    return f"{report_id}|{int(pos)}"


def parse_table_ids(value: Any) -> set[str]:
    """Parse gold-table strings, including bare `|33` after a full report id."""
    out: set[str] = set()
    current_report = ""
    for raw in flatten(value):
        text = re.sub(r"\([^)]*\)", "", str(raw))
        for token in re.split(r"[;,&]+", text):
            token = token.strip()
            if not token:
                continue
            full = _FULL_TABLE_ID.search(token)
            if full:
                current_report = full.group(1)
                out.add(_normalize_table_id(current_report, full.group(2)))
                continue
            bare = _BARE_TABLE_POS.match(token)
            if bare and current_report:
                out.add(_normalize_table_id(current_report, bare.group(1)))
    return out


def gold_tables(qid: int, gold_row: dict[str, Any], evalset: dict[int, dict[str, Any]]) -> set[str]:
    from_eval = parse_table_ids((evalset.get(qid) or {}).get("gt_tables"))
    return from_eval or parse_table_ids(gold_row.get("evidence_table_id"))


def submitted_tables(rec: dict[str, Any] | None) -> set[str]:
    if rec is None:
        return set()
    return set(
        rec.get("table_ids")
        or (rec.get("item") or {}).get("relevant_tables")
        or rec.get("relevant_tables")
        or []
    )


def used_tables(rec: dict[str, Any] | None) -> set[str]:
    if rec is None:
        return set()
    diag = rec.get("diag") or {}
    out = set(diag.get("evidence_tables") or rec.get("evidence_tables") or [])

    formula = diag.get("formula_facts") or {}
    for fact in formula.get("facts") or []:
        table_id = fact.get("table_id")
        if table_id:
            out.add(str(table_id))

    for ev in (rec.get("item") or {}).get("evidence") or []:
        csv_path = str(ev.get("csv_path") or "")
        match = _CSV_TABLE_PATH.search(Path(csv_path).name)
        if match:
            out.add(_normalize_table_id(match.group(1), match.group(2)))
    return out


def reach_bucket(want: set[str], used: set[str], submitted: set[str]) -> str:
    if not want:
        return "no_gold_table_label"
    if want <= used:
        return "all_gold_used"
    if want & used:
        return "some_gold_used"
    if want <= submitted:
        return "all_gold_retrieved_not_used"
    if want & submitted:
        return "some_gold_retrieved_not_used"
    return "no_gold_retrieved"


def question_level(qid: int, evalset: dict[int, dict[str, Any]], questions: dict[int, dict[str, Any]]) -> str:
    if qid in evalset:
        return str(evalset[qid].get("level") or "?").split(".", 1)[0]
    row = questions.get(qid) or {}
    if row.get("answer_shape") == "single_cell":
        return "shape_single_cell"
    if row.get("multi_year") and row.get("multi_company"):
        return "shape_multi_year_company"
    if row.get("multi_year"):
        return "shape_temporal"
    if row.get("multi_company"):
        return "shape_cross_company"
    return "shape_other"


def first_capability_attempt(rec: dict[str, Any] | None) -> str:
    if rec is None:
        return "missing"
    router = ((rec.get("diag") or {}).get("capability_router") or {})
    decisions = router.get("decisions") or {}
    for name in router.get("order") or []:
        decision = decisions.get(name) or {}
        if decision.get("attempt"):
            return str(name)
    return str(rec.get("solver") or "unknown")


def formula_gate_reason(rec: dict[str, Any] | None) -> str:
    if rec is None:
        return "missing"
    diag = rec.get("diag") or {}
    router_formula = (
        ((diag.get("capability_router") or {}).get("decisions") or {}).get("formula_facts")
        or {}
    )
    if router_formula:
        if router_formula.get("attempt"):
            return "attempt"
        return str(router_formula.get("reason") or "blocked")
    for error in rec.get("errors") or []:
        text = str(error)
        if text.startswith("formula_facts:"):
            return text.split(":", 1)[1].strip() or "blocked"
    formula = diag.get("formula_facts") or {}
    if formula.get("done"):
        return "attempt"
    if formula.get("reason"):
        return str(formula["reason"])
    return "no_trace"


def failure_bucket(rec: dict[str, Any] | None, ok: bool, reach: str) -> str:
    if ok:
        return "correct"
    if rec is None:
        return "missing_from_run"
    if rec.get("status") not in {None, "", "ok"}:
        return "run_status_error"

    pred = answer_of(rec)
    diag = rec.get("diag") or {}
    if pred is None:
        return "answer_none"
    if pred == 0.0:
        return "zero_answer"
    if (diag.get("units") or {}).get("failed"):
        return "unit_failed"

    solver = str(rec.get("solver") or "unknown")
    if solver == "formula_facts":
        return "formula_facts_wrong"
    if solver == "cell_locator":
        return "cell_locator_wrong"
    if solver == "selection":
        return "selection_wrong"

    if reach in {"all_gold_used", "some_gold_used"}:
        return "wrong_gold_used"
    if reach in {"all_gold_retrieved_not_used", "some_gold_retrieved_not_used"}:
        return "wrong_gold_retrieved_not_used"
    if reach == "no_gold_retrieved":
        return "wrong_no_gold_retrieved"
    return "wrong_no_gold_table_label"


def solver_name(rec: dict[str, Any] | None) -> str:
    if rec is None:
        return "missing"
    return str(rec.get("solver") or "unknown")


def has_detector(rec: dict[str, Any] | None, name: str) -> bool:
    if rec is None:
        return name == "missing"
    diag = rec.get("diag") or {}
    if name == "verify_false":
        verify = diag.get("verify") or {}
        return verify.get("correct") is False
    if name == "zero_or_none":
        pred = answer_of(rec)
        return pred is None or pred == 0.0
    if name == "unit_failed":
        return bool((diag.get("units") or {}).get("failed"))
    if name == "execution_error":
        if rec.get("status") not in {None, "", "ok"}:
            return True
        return any(
            re.search(r"\b(TypeError|ValueError|KeyError|IndexError|SyntaxError)\b", str(error))
            for error in rec.get("errors") or []
        )
    return False


def summarize(rows: list[dict[str, Any]], key: str) -> list[tuple[str, int, int, list[int]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    out = []
    for label, items in grouped.items():
        ok = sum(1 for item in items if item["correct"])
        miss_ids = [int(item["id"]) for item in items if not item["correct"]]
        out.append((label, ok, len(items), miss_ids))
    return sorted(out, key=lambda item: (-item[2], item[0]))


def print_summary(rows: list[dict[str, Any]], run_path: Path) -> None:
    total = len(rows)
    correct = sum(1 for row in rows if row["correct"])
    print(f"{run_path}: {correct}/{total} ({correct / total:.1%})")

    for title, key in (
        ("by failure bucket", "failure_bucket"),
        ("by solver", "solver"),
        ("by first capability attempt", "first_capability_attempt"),
        ("by question level", "level"),
        ("by gold-table reach", "reach"),
    ):
        print(f"\n{title}:")
        for label, ok, n, miss_ids in summarize(rows, key):
            suffix = f" miss={miss_ids}" if miss_ids else ""
            print(f"  {label:<35} {ok:>2}/{n:<2} ({ok / n:5.1%}){suffix}")

    print("\nformula_facts gate reasons:")
    for reason, count in Counter(str(row["formula_gate_reason"]) for row in rows).most_common():
        miss_ids = [int(row["id"]) for row in rows if row["formula_gate_reason"] == reason and not row["correct"]]
        suffix = f" miss={miss_ids}" if miss_ids else ""
        print(f"  {reason:<45} {count:>2}{suffix}")

    print("\ndetectors on gold:")
    for detector in ("verify_false", "zero_or_none", "unit_failed", "execution_error"):
        flagged = [row for row in rows if row["detectors"].get(detector)]
        wrong = [row for row in flagged if not row["correct"]]
        print(f"  {detector:<16} flagged={len(flagged):>2} wrong={len(wrong):>2} ids={[int(r['id']) for r in wrong]}")


def build_rows(run_path: Path, *, min_confidence: str, tol: float) -> list[dict[str, Any]]:
    gold = load_gold(min_confidence)
    run = load_run(run_path)
    evalset = load_evalset()
    questions = load_questions()

    rows: list[dict[str, Any]] = []
    for qid, gold_row in sorted(gold.items()):
        rec = run.get(qid)
        pred = answer_of(rec)
        gold_answer = float(gold_row["gold_answer"])
        ok = close(pred, gold_answer, tol, year_answer=is_year_answer(gold_row))
        want = gold_tables(qid, gold_row, evalset)
        used = used_tables(rec)
        submitted = submitted_tables(rec)
        reach = reach_bucket(want, used, submitted)
        rows.append(
            {
                "id": qid,
                "level": question_level(qid, evalset, questions),
                "question": gold_row.get("question") or (questions.get(qid) or {}).get("question", ""),
                "gold_answer": gold_answer,
                "answer": pred,
                "correct": ok,
                "solver": solver_name(rec),
                "first_capability_attempt": first_capability_attempt(rec),
                "formula_gate_reason": formula_gate_reason(rec),
                "reach": reach,
                "gold_tables": sorted(want),
                "used_tables": sorted(used),
                "submitted_gold_tables": sorted(want & submitted),
                "failure_bucket": failure_bucket(rec, ok, reach),
                "detectors": {
                    name: has_detector(rec, name)
                    for name in ("verify_false", "zero_or_none", "unit_failed", "execution_error")
                },
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", type=Path)
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL)
    ap.add_argument("--min-confidence", default="medium", choices=["high", "medium", "low"])
    ap.add_argument("--json-out", type=Path, help="optional machine-readable row output")
    args = ap.parse_args()

    rows = build_rows(args.run, min_confidence=args.min_confidence, tol=args.tol)
    print_summary(rows, args.run)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
