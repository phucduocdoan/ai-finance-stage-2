"""Retrieve node: get relevant table_ids for a question.

Phase 1: reads from a pre-computed JSONL cache (frozen retrieval).
Phase 2: replace _retrieve_live() with the real BGE retriever call.
"""
from __future__ import annotations

import json
from pathlib import Path

from finance_qa.graph.state import FinanceState
from finance_qa.paths import RUNS_DIR

# Default cache: the frozen retrieval run used for regen
_DEFAULT_CACHE = RUNS_DIR / "full_1012.jsonl"

_CACHE: dict[int, list[str]] | None = None


def _load_cache(path: Path) -> dict[int, list[str]]:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for line in filter(str.strip, fh):
                    r = json.loads(line)
                    qid = int(r["id"])
                    tids = r.get("table_ids") or []
                    if qid not in _CACHE:  # first-wins (or last-wins, consistent)
                        _CACHE[qid] = tids
    return _CACHE


def retrieve(state: FinanceState, cache_path: Path = _DEFAULT_CACHE) -> dict:
    cache = _load_cache(cache_path)
    table_ids = cache.get(state["id"], [])
    return {"table_ids": table_ids, "errors": state.get("errors", []) + (
        [f"retrieve: no table_ids for Q{state['id']}"] if not table_ids else []
    )}
