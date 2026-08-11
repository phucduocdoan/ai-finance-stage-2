"""Quick test: formula solver on representative ratio/agg questions.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/test_formula_solver.py
  PYTHONPATH=src .venv_bge/bin/python scripts/test_formula_solver.py --id 363 371 368

Shows: route taken, canonical data available, LLM code generated, final answer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from finance_qa.agents.finance.graph import run_question

ROOT = Path(__file__).parent.parent

# Gold answers from extended_gold.jsonl (where available)
_GOLD: dict[int, float] = {}
_FROZEN: dict[int, dict] = {}


def _load_refs():
    global _GOLD, _FROZEN
    if not _GOLD:
        for r in [json.loads(l) for l in (ROOT / "data/eval/extended_gold.jsonl").open()]:
            _GOLD[int(r["id"])] = float(r["answer"])
    if not _FROZEN:
        for r in [json.loads(l) for l in (ROOT / "artifacts/runs/regen_frozen_patched.jsonl").open()]:
            _FROZEN[int(r["id"])] = r


def _load_question(qid: int) -> str:
    _load_refs()
    if qid in _FROZEN:
        return _FROZEN[qid].get("question", "")
    for r in [json.loads(l) for l in (ROOT / "data/metadata/questions_enriched.jsonl").open()]:
        if int(r["id"]) == qid:
            return r["question"]
    return ""


# Default: ratio+canonical questions from probe output
DEFAULT_IDS = [
    363,  # D/E → ICR multi-year (gold=3.32)
    365,  # biên lợi nhuận gộp giai đoạn
    368,  # quick ratio < 1, multi-company
    371,  # biên lợi nhuận gộp cao nhất, multi-company
    375,  # chênh lệch quick ratio
    370,  # lưu chuyển tiền kinh doanh, multi-company
]


def test_one(qid: int) -> None:
    _load_refs()
    question = _load_question(qid)
    if not question:
        print(f"Q{qid}: not found"); return

    print(f"\n{'='*65}")
    print(f"Q{qid}: {question[:75]}")

    state = run_question(qid, question)

    gold   = _GOLD.get(qid)
    frozen = _FROZEN.get(qid, {}).get("answer")
    solver = state["solver"]
    ans    = state["answer"]

    print(f"  solver:   {solver}")
    print(f"  answer:   {ans}")
    if gold is not None:
        ok = abs(ans - gold) / max(abs(gold), 1e-6) < 0.01
        print(f"  gold:     {gold}  {'✓' if ok else '✗'}")
    if frozen is not None:
        print(f"  frozen:   {frozen}")

    print(f"  query:    {state.get('pandas_query','')[:100]}")
    if state.get("errors"):
        for e in state["errors"]:
            print(f"  note:     {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", nargs="+", type=int, default=DEFAULT_IDS)
    args = ap.parse_args()
    for qid in args.id:
        test_one(qid)
    print()


if __name__ == "__main__":
    main()
