"""Public RAG service used by finance QA pipelines."""
from __future__ import annotations

import json
from typing import Any, Mapping

from finance_qa.core.paths import RUNS_DIR
from finance_qa.modules.rag.candidates import CandidateRetriever

_PRIMARY = frozenset({"balance_sheet", "income_statement", "cash_flow", "equity_change"})
_retrievers: dict[tuple[str | None, int], CandidateRetriever] = {}
_frozen: dict[int, list[str]] | None = None


def get_retriever(reranker: str | None, judge_top_n: int) -> CandidateRetriever:
    """Return a cached configured retriever."""
    key = (reranker, judge_top_n)
    if key not in _retrievers:
        _retrievers[key] = CandidateRetriever(
            load_judge_text=True,
            reranker=reranker,
            judge_top_n=judge_top_n,
        )
    return _retrievers[key]


def frozen_table_ids(question_id: int) -> list[str]:
    """Fallback table ids from the frozen full run, when available."""
    global _frozen
    if _frozen is None:
        _frozen = {}
        cache = RUNS_DIR / "full_1012.jsonl"
        if cache.exists():
            with cache.open(encoding="utf-8") as fh:
                for line in filter(str.strip, fh):
                    row = json.loads(line)
                    _frozen[int(row["id"])] = row.get("table_ids") or []
    return _frozen.get(question_id, [])


def retrieve_table_ids(
    question: str,
    question_id: int,
    tickers: list[str],
    years: list[int],
    doc_type: str,
    *,
    reranker: str | None,
    judge_top_n: int,
    frozen_fallback: bool,
) -> tuple[list[str], list[str]]:
    """Select relevant table ids for a finance question."""
    errors: list[str] = []

    def _fallback(reason: str) -> tuple[list[str], list[str]]:
        errors.append(reason)
        if frozen_fallback:
            return frozen_table_ids(question_id), errors
        return [], errors

    if not tickers or not years:
        return _fallback("retrieve: no tickers/years -> frozen fallback")

    question_dict = {
        "question": question,
        "tickers": tickers,
        "years": years,
        "doc_type": doc_type or "unknown",
    }

    try:
        retriever = get_retriever(reranker, judge_top_n)
        pool = retriever.build_pool(question_dict)
        result = retriever.select(question_dict, pool, thinking=False)
        picks = result["picks"]
        primary = [
            key
            for key in pool.ranked
            if retriever.statement_types.get(key) in _PRIMARY and key not in set(picks)
        ]
        table_ids = picks + primary
    except Exception as exc:  # noqa: BLE001 - use frozen retrieval if configured
        return _fallback(f"retrieve: error: {exc} -> frozen fallback")

    if not table_ids:
        return _fallback("retrieve: empty result -> frozen fallback")
    return table_ids, errors


def make_retrieve_node(cfg):
    """Build the LangGraph retrieve node bound to agent config ``cfg``."""

    def retrieve(state: Mapping[str, Any]) -> dict[str, Any]:
        table_ids, retrieve_errors = retrieve_table_ids(
            state["question"],
            int(state["id"]),
            list(state.get("tickers") or []),
            list(state.get("years") or []),
            str(state.get("doc_type") or "unknown"),
            reranker=cfg.reranker,
            judge_top_n=cfg.judge_top_n,
            frozen_fallback=cfg.frozen_fallback,
        )
        return {
            "table_ids": table_ids,
            "errors": list(state.get("errors") or []) + retrieve_errors,
        }

    return retrieve

