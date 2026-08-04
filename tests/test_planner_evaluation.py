"""Regression tests for planner benchmark scoring and label coverage."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.evaluation.planner import load_cases, score_answer, summarize


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


cases = load_cases()
check("all table-ground-truth cases have labels", len(cases) == 15)
check("equivalent tables use first verified choice", len(cases[5]["table_ids"]) == 1)

label = {
    "expected": 100.0,
    "abs_tolerance": 0.001,
    "rel_tolerance": 0.000001,
}
check("answer inside absolute tolerance passes", score_answer(100.0005, label)["correct"])
check("answer outside tolerance fails", not score_answer(100.01, label)["correct"])
check("non-numeric answer fails safely", score_answer("bad", label)["predicted"] is None)

base = {
    "level": "L1.1",
    "executable": True,
    "latency_seconds": 2.0,
    "planner_success": True,
    "fallback_success": False,
    "planner_error": "",
    "error": "",
    "predicted": 1.0,
    "expected": 1.0,
    "status": "correct_planner",
}
records = [
    {**base, "qid": 1, "correct": True},
    {
        **base,
        "qid": 2,
        "correct": False,
        "planner_success": False,
        "fallback_success": True,
        "status": "wrong_fallback_answer",
    },
]
summary = summarize(records)
check("overall accuracy is aggregated", summary["overall"]["accuracy"] == 0.5)
check("planner precision is separate from fallback", summary["overall"]["planner_precision"] == 1.0)
check("failure details are retained", summary["failures"][0]["qid"] == 2)

print("tất cả PASS")
