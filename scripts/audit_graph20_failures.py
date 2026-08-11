"""Audit current GRAPH20 failures at the canonical-plan/fact level.

The report is for debugging general planning gaps, not for adding question-id
rules. It runs the real graph prefix (understand -> retrieve -> load), asks for
the same Pydantic CanonicalPlan used by formula_solver, executes it
deterministically, and dumps the selected facts.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/audit_graph20_failures.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, "src")

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.understand import make_understand
from finance_qa.modules.codegen.formula import _collect_canonical, infer_canonical_plan
from finance_qa.modules.data.service import load_node
from finance_qa.modules.data.preprocessing.questions import detect_unit
from finance_qa.modules.rag.service import make_retrieve_node
from finance_qa.modules.tools.metrics import (
    _apply_filters,
    _candidate_rows,
    _metrics_with_context,
    _pick_row,
    convert_unit,
    execute_canonical_plan,
    metric_value,
)
from finance_qa.pipelines.finance_qa import make_initial_state


DEFAULT_FAILED_IDS = [392, 409, 414, 415, 423, 424, 429, 439, 440]
AUDIT_DIR = Path("artifacts/audits")


def _load_gold() -> dict[int, dict[str, Any]]:
    gold: dict[int, dict[str, Any]] = {}
    with open("data/eval/extended_gold.jsonl", encoding="utf-8") as fh:
        for line in filter(str.strip, fh):
            row = json.loads(line)
            gold[int(row["id"])] = row
    return gold


def _rel_ok(pred: float | None, expected: float) -> bool:
    if pred is None:
        return False
    denom = abs(expected) if abs(expected) > 1e-9 else 1.0
    return abs(float(pred) - expected) / denom < 0.01


def _metrics_subset(metrics: dict[str, float], metric_ids: list[str]) -> dict[str, float | None]:
    return {metric: metric_value(metrics, metric) for metric in metric_ids}


def _plan_metric_ids(plan: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for filt in plan.get("filters") or []:
        metric = filt.get("metric") if isinstance(filt, dict) else None
        if metric:
            result.append(str(metric))
    select = plan.get("select")
    if isinstance(select, dict) and select.get("metric"):
        result.append(str(select["metric"]))
    answer = plan.get("answer")
    if isinstance(answer, dict) and answer.get("metric"):
        result.append(str(answer["metric"]))
    seen = set()
    return [m for m in result if not (m in seen or seen.add(m))]


def _trace_execution(
    data: dict[str, dict[str, dict[str, float]]],
    plan: dict[str, Any],
    *,
    tickers: list[str],
    years: list[int],
    unit_hint: str,
) -> dict[str, Any]:
    metric_ids = _plan_metric_ids(plan)
    rows = _candidate_rows(data, tickers, years)
    before = [
        {
            "ticker": row["ticker"],
            "year": row["year"],
            "metrics": _metrics_subset(row["metrics"], metric_ids),
        }
        for row in rows
    ]
    filtered = _apply_filters(rows, plan.get("filters") or [])
    if filtered is None:
        return {"candidate_rows": before, "filter_error": True}
    after = [
        {
            "ticker": row["ticker"],
            "year": row["year"],
            "metrics": _metrics_subset(row["metrics"], metric_ids),
        }
        for row in filtered
    ]

    selected = None
    select = plan.get("select") if isinstance(plan.get("select"), dict) else {}
    if select:
        selected = _pick_row(filtered, select)
        if selected and select.get("offset_years"):
            shifted_year = int(selected["year"]) + int(select.get("offset_years") or 0)
            shifted_metrics = _metrics_with_context(data.get(selected["ticker"], {}), shifted_year)
            selected = (
                {"ticker": selected["ticker"], "year": shifted_year, "metrics": shifted_metrics}
                if shifted_metrics is not None
                else None
            )
    elif len(filtered) == 1:
        selected = filtered[0]

    answer = plan.get("answer") if isinstance(plan.get("answer"), dict) else {}
    answer_metric = str(answer.get("metric") or "")
    raw = metric_value(selected["metrics"], answer_metric) if selected and answer_metric else None
    converted = (
        convert_unit(float(raw), answer_metric, str(answer.get("unit") or unit_hint))
        if raw is not None
        else None
    )
    return {
        "candidate_rows": before,
        "filtered_rows": after,
        "selected": (
            {
                "ticker": selected["ticker"],
                "year": selected["year"],
                "metrics": _metrics_subset(selected["metrics"], metric_ids),
            }
            if selected
            else None
        ),
        "raw_answer": raw,
        "converted_answer": converted,
    }


def audit_one(qid: int, cfg: FinanceAgentConfig) -> dict[str, Any]:
    gold = _load_gold()[qid]
    state = make_initial_state(qid, gold["question"])
    state.update(make_understand(cfg)(state))
    state.update(make_retrieve_node(cfg)(state))
    state.update(load_node(state))

    data = _collect_canonical(state.get("frames") or {}, state.get("names") or {})
    plan_obj = infer_canonical_plan(gold["question"])
    plan = plan_obj.model_dump(exclude_none=True) if plan_obj is not None else None

    deterministic = None
    trace: dict[str, Any] = {}
    if plan and not plan.get("unsupported"):
        deterministic = execute_canonical_plan(
            data,
            plan,
            default_tickers=state.get("tickers") or [],
            default_years=state.get("years") or [],
            unit_hint=state.get("unit_hint") or detect_unit(gold["question"]),
        )
        trace = _trace_execution(
            data,
            plan,
            tickers=state.get("tickers") or [],
            years=state.get("years") or [],
            unit_hint=state.get("unit_hint") or detect_unit(gold["question"]),
        )

    pred = deterministic[0] if deterministic is not None else None
    return {
        "id": qid,
        "question": gold["question"],
        "expected": float(gold["answer"]),
        "predicted": pred,
        "match": _rel_ok(pred, float(gold["answer"])),
        "understand": {
            key: state.get(key)
            for key in ("tickers", "years", "operation", "metric", "unit_hint", "answer_shape")
        },
        "table_ids": state.get("table_ids") or [],
        "canonical_coverage": {
            ticker: {year: sorted(metrics) for year, metrics in years.items()}
            for ticker, years in data.items()
        },
        "plan": plan,
        "query": deterministic[1] if deterministic is not None else None,
        "trace": trace,
        "errors": state.get("errors") or [],
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        if math.isfinite(value):
            return f"{value:.8g}"
    return str(value)


def write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    lines = ["# GRAPH20 Failure Audit", ""]
    for row in rows:
        lines.append(f"## Q{row['id']}")
        lines.append("")
        lines.append(row["question"])
        lines.append("")
        lines.append(
            f"- expected: `{_fmt(row['expected'])}`; predicted: `{_fmt(row['predicted'])}`; "
            f"match: `{row['match']}`"
        )
        lines.append(f"- understand: `{json.dumps(row['understand'], ensure_ascii=False)}`")
        lines.append(f"- query: `{row.get('query')}`")
        lines.append("")
        lines.append("Plan:")
        lines.append("```json")
        lines.append(json.dumps(row.get("plan"), ensure_ascii=False, indent=2))
        lines.append("```")
        trace = row.get("trace") or {}
        selected = trace.get("selected")
        lines.append(f"Selected: `{json.dumps(selected, ensure_ascii=False)}`")
        lines.append("")
        lines.append("Filtered rows:")
        for item in (trace.get("filtered_rows") or [])[:20]:
            lines.append(f"- `{json.dumps(item, ensure_ascii=False)}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default=",".join(map(str, DEFAULT_FAILED_IDS)))
    parser.add_argument("--out", type=Path, default=AUDIT_DIR / "graph20_failures.jsonl")
    parser.add_argument("--md", type=Path, default=AUDIT_DIR / "graph20_failures.md")
    args = parser.parse_args()

    ids = [int(raw) for raw in args.ids.split(",") if raw.strip()]
    cfg = FinanceAgentConfig()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with args.out.open("w", encoding="utf-8") as fh:
        for qid in ids:
            row = audit_one(qid, cfg)
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            mark = "OK" if row["match"] else "MISS"
            print(
                f"{qid:>4} {mark:>4} expected={_fmt(row['expected'])} "
                f"pred={_fmt(row['predicted'])} query={row.get('query')}"
            )
    write_markdown(rows, args.md)
    print(f"\nwrote {args.out}")
    print(f"wrote {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
