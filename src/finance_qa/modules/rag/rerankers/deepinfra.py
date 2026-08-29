"""DeepInfra reranker backend.

See also `indexing/deepinfra.py` for the embedding backend -- same
provider, different pipeline stage, easy to open the wrong one by filename.
"""
from __future__ import annotations

from typing import Sequence

from finance_qa.core.http import run_sync
from finance_qa.modules.rag.deepinfra_client import (
    INFERENCE_URL,
    DeepInfraClient,
    DeepInfraError,
)


RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"


def _scores(data: dict, n: int) -> list[float]:
    scores = data.get("scores")
    if scores is None or len(scores) != n:
        raise DeepInfraError(
            f"reranker returned {None if scores is None else len(scores)} scores "
            f"for {n} documents: {str(data)[:200]}"
        )
    return [float(score) for score in scores]


async def arerank(
    query: str,
    documents: Sequence[str],
    *,
    model: str = RERANK_MODEL,
    key: str | None = None,
    client: DeepInfraClient | None = None,
) -> list[float]:
    """Relevance score per document, in input order. Higher is more relevant."""
    if not documents:
        return []
    payload = {
        "queries": [query] * len(documents),
        "documents": [document if document.strip() else " " for document in documents],
    }
    data = await (client or DeepInfraClient(key=key)).apost(
        f"{INFERENCE_URL}/{model}", payload
    )
    return _scores(data, len(documents))


def rerank(
    query: str,
    documents: Sequence[str],
    *,
    model: str = RERANK_MODEL,
    key: str | None = None,
    client: DeepInfraClient | None = None,
) -> list[float]:
    return run_sync(arerank(query, documents, model=model, key=key, client=client))


class DeepInfraReranker:
    """`RerankerClient` over the DeepInfra inference route."""

    def __init__(self, model: str = RERANK_MODEL, *, client: DeepInfraClient | None = None) -> None:
        self.model = model
        self.name = model.rsplit("/", 1)[-1]
        self.client = client

    async def ascores(self, query: str, documents: Sequence[str]) -> list[float]:
        return await arerank(query, documents, model=self.model, client=self.client)

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        return rerank(query, documents, model=self.model, client=self.client)
