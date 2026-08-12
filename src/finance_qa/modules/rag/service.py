"""Public RAG service used by finance QA pipelines."""
from __future__ import annotations

import asyncio
import json
import threading
from functools import lru_cache
from typing import Any, Mapping

from finance_qa.core.http import pool as loop_cache
from finance_qa.core.http import run_sync
from finance_qa.core.paths import RUNS_DIR
from finance_qa.modules.rag.candidates import CandidateRetriever

_PRIMARY = frozenset({"balance_sheet", "income_statement", "cash_flow", "equity_change"})
_retriever_lock = threading.Lock()
_frozen: dict[int, list[str]] | None = None


@lru_cache(maxsize=None)
def _build_retriever(reranker: str | None, judge_top_n: int) -> CandidateRetriever:
    return CandidateRetriever(
        load_judge_text=True,
        reranker=reranker,
        judge_top_n=judge_top_n,
    )


def get_retriever(reranker: str | None, judge_top_n: int) -> CandidateRetriever:
    """Return the process-wide retriever for this config, built exactly once.

    lru_cache alone is not enough: it evaluates the wrapped function *outside*
    its own lock, so the 8 run_graph workers hitting a cold cache each build a
    retriever (measured: 8/8 builds; RSS 14.5 GB from duplicate bge-m3 and dense
    index copies). The lock makes construction happen once; afterwards this is a
    dict hit.
    """
    with _retriever_lock:
        return _build_retriever(reranker, judge_top_n)


async def aget_retriever(reranker: str | None, judge_top_n: int) -> CandidateRetriever:
    """`get_retriever` off the event loop.

    The build takes ~30 s (146k metadata rows, BM25 IDF, dense index, bge-m3), so
    running it inline would stall every other question's in-flight HTTP call. The
    asyncio lock is what keeps that to a single thread hop: without it, every
    concurrent question would send its own thread in to block on
    `_retriever_lock`. Once warm, this is a dict hit in a thread.
    """
    cache = loop_cache()
    lock = cache.get("retriever_lock")
    if lock is None:
        lock = cache["retriever_lock"] = asyncio.Lock()
    async with lock:
        return await asyncio.to_thread(get_retriever, reranker, judge_top_n)


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


def _evidence(retriever: CandidateRetriever, pool, picks: list[str]) -> list[str]:
    """Judge picks first, then the shortlisted primary statements they missed."""
    chosen = set(picks)
    primary = [
        key
        for key in pool.ranked
        if retriever.statement_types.get(key) in _PRIMARY and key not in chosen
    ]
    return picks + primary


async def aretrieve_table_ids(
    question: str,
    question_id: int,
    tickers: list[str],
    years: list[int],
    doc_type: str,
    *,
    reranker: str | None,
    judge_top_n: int,
    frozen_fallback: bool,
    judge_thinking: bool = False,
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
        retriever = await aget_retriever(reranker, judge_top_n)
        pool = await retriever.abuild_pool(question_dict)
        result = await retriever.aselect(question_dict, pool, thinking=judge_thinking)
        table_ids = _evidence(retriever, pool, result["picks"])
    except Exception as exc:  # noqa: BLE001 - use frozen retrieval if configured
        return _fallback(f"retrieve: error: {exc} -> frozen fallback")

    if not table_ids:
        return _fallback("retrieve: empty result -> frozen fallback")
    return table_ids, errors


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
    """Sync `aretrieve_table_ids`, for single-question scripts."""
    return run_sync(
        aretrieve_table_ids(
            question,
            question_id,
            tickers,
            years,
            doc_type,
            reranker=reranker,
            judge_top_n=judge_top_n,
            frozen_fallback=frozen_fallback,
        )
    )


def make_retrieve_node(cfg):
    """Build the LangGraph retrieve node bound to agent config ``cfg``."""

    async def retrieve(state: Mapping[str, Any]) -> dict[str, Any]:
        table_ids, retrieve_errors = await aretrieve_table_ids(
            state["question"],
            int(state["id"]),
            list(state.get("tickers") or []),
            list(state.get("years") or []),
            str(state.get("doc_type") or "unknown"),
            reranker=cfg.reranker,
            judge_top_n=cfg.judge_top_n,
            frozen_fallback=cfg.frozen_fallback,
            judge_thinking=cfg.judge_thinking,
        )
        return {
            "table_ids": table_ids,
            "errors": list(state.get("errors") or []) + retrieve_errors,
        }

    return retrieve

