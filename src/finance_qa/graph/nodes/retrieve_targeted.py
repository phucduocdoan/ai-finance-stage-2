"""Retrieve node (targeted): BM25+dense → Qwen3-Reranker-0.6B → LLM judge.

Pipeline:
  shortlist(ticker+year) → BM25 top-20 + dense top-20 → RRF ~40 tables
    → Qwen3-Reranker-0.6B cross-encoder rerank
    → judge_top_n=20 best-ordered tables → LLM judge (thinking=False)

The reranker fixes the judge quality problem: with RRF ordering, judge
(thinking=False) made poor selections from 40 poorly-ranked tables.
With a cross-encoder reranking first, the top-20 tables are well-ordered
and the judge reliably picks the right ones.

Fallback to frozen cache when tickers/years unknown or retriever fails.
"""
from __future__ import annotations

import json

from finance_qa.graph.state import FinanceState
from finance_qa.paths import RUNS_DIR
from finance_qa.retrieval.candidates import CandidateRetriever

_PRIMARY = frozenset({"balance_sheet", "income_statement", "cash_flow", "equity_change"})

# ── lazy singletons ──────────────────────────────────────────────────────────

_retriever: CandidateRetriever | None = None
_frozen: dict[int, list[str]] | None = None


def _get_retriever() -> CandidateRetriever:
    global _retriever
    if _retriever is None:
        _retriever = CandidateRetriever(
            load_judge_text=True,
            reranker="qwen3-0.6b",  # cross-encoder rerank ~40 → best-ordered
            judge_top_n=20,          # judge sees top-20 reranked tables
        )
    return _retriever


def _get_frozen(qid: int) -> list[str]:
    global _frozen
    if _frozen is None:
        _frozen = {}
        cache = RUNS_DIR / "full_1012.jsonl"
        if cache.exists():
            with cache.open(encoding="utf-8") as fh:
                for line in filter(str.strip, fh):
                    r = json.loads(line)
                    _frozen[int(r["id"])] = r.get("table_ids") or []
    return _frozen.get(qid, [])


# ── node ─────────────────────────────────────────────────────────────────────

def retrieve_targeted(state: FinanceState) -> dict:
    tickers = state.get("tickers") or []
    years   = state.get("years") or []
    qid     = state["id"]
    errors  = list(state.get("errors") or [])

    if not tickers or not years:
        errors.append("retrieve_targeted: no tickers/years → frozen fallback")
        return {"table_ids": _get_frozen(qid), "errors": errors}

    question_dict = {
        "question": state["question"],
        "tickers":  tickers,
        "years":    years,
        "doc_type": state.get("doc_type") or "unknown",
    }

    try:
        retriever = _get_retriever()
        pool      = retriever.build_pool(question_dict)
        result    = retriever.select(question_dict, pool, thinking=False)
        picks     = result["picks"]

        # Always include primary statements (BS/IS/CF) even if judge didn't pick them.
        primary = [
            key for key in pool.ranked
            if retriever.statement_types.get(key) in _PRIMARY
            and key not in set(picks)
        ]
        table_ids = picks + primary

    except Exception as e:
        errors.append(f"retrieve_targeted: error: {e} → frozen fallback")
        return {"table_ids": _get_frozen(qid), "errors": errors}

    if not table_ids:
        errors.append("retrieve_targeted: empty result → frozen fallback")
        return {"table_ids": _get_frozen(qid), "errors": errors}

    return {"table_ids": table_ids, "errors": errors}
