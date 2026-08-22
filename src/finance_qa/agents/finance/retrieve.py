"""The `retrieve` node: adapts `modules.rag.service` to the graph's state dict."""
from __future__ import annotations

from typing import Any, Mapping

from finance_qa.modules.rag.service import aretrieve_table_ids


def make_retrieve_node(cfg):
    """Build the LangGraph retrieve node bound to agent config ``cfg``."""

    async def retrieve(state: Mapping[str, Any]) -> dict[str, Any]:
        table_ids, shortlist, retrieve_errors = await aretrieve_table_ids(
            state["question"],
            int(state["id"]),
            list(state.get("tickers") or []),
            list(state.get("years") or []),
            str(state.get("doc_type") or "unknown"),
            reranker=cfg.reranker,
            judge_top_n=cfg.judge_top_n,
            dense_backend=cfg.dense_backend,
            frozen_fallback=cfg.frozen_fallback,
            judge_thinking=cfg.judge_thinking,
        )
        return {
            "table_ids": table_ids,
            # Everything past the hard filter, for `find_rows` to search. Not
            # submitted — `table_ids` is the scored list.
            "shortlist": shortlist,
            "errors": list(state.get("errors") or []) + retrieve_errors,
        }

    return retrieve
