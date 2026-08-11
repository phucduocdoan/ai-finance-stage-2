"""Test the LangGraph pipeline on representative questions.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/test_graph.py
  PYTHONPATH=src .venv_bge/bin/python scripts/test_graph.py --id 1 363 422

Tests one question from each routing branch:
  single_cell (not multi)  → lookup_solver   e.g. Q1
  derived / multi_year     → repl_solver     e.g. Q363, Q440
"""
from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401

from finance_qa.agents.finance.graph import run_question

# Baseline from frozen run for comparison
_FROZEN: dict[int, dict] | None = None


def _load_frozen() -> dict[int, dict]:
    global _FROZEN
    if _FROZEN is None:
        _FROZEN = {}
        import os
        path = "artifacts/runs/regen_frozen_patched.jsonl"
        if os.path.exists(path):
            with open(path) as f:
                for l in f:
                    r = json.loads(l)
                    _FROZEN[r["id"]] = r
    return _FROZEN


# Default test questions: one per routing branch
DEFAULT_IDS = [
    1,    # single_cell, not multi → lookup
    3,    # single_cell, not multi → lookup
    363,  # derived, multi_year   → repl
    440,  # derived, multi_year   → repl
]


def _load_question(qid: int) -> str:
    frozen = _load_frozen()
    if qid in frozen:
        return frozen[qid].get("question", "")
    import json
    from finance_qa.core.paths import QUESTION_METADATA_PATH
    with QUESTION_METADATA_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if int(r["id"]) == qid:
                return r["question"]
    return ""


def test_one(qid: int) -> None:
    question = _load_question(qid)
    if not question:
        print(f"Q{qid}: not found"); return

    print(f"\n{'='*60}")
    print(f"Q{qid}: {question[:80]}")

    state = run_question(qid, question)

    frozen = _load_frozen().get(qid, {})
    frozen_ans = frozen.get("answer")

    print(f"  solver:   {state['solver']}")
    print(f"  answer:   {state['answer']}")
    print(f"  frozen:   {frozen_ans}")
    print(f"  query:    {state['pandas_query'][:90]}")
    if state.get("errors"):
        print(f"  errors:   {state['errors']}")
    route_used = "lookup" if state["solver"] == "lookup" else "repl"
    print(f"  route:    {state.get('answer_shape')} | multi_year={state.get('multi_year')} → {route_used}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", nargs="+", type=int, default=DEFAULT_IDS)
    args = ap.parse_args()

    for qid in args.id:
        test_one(qid)


if __name__ == "__main__":
    main()
