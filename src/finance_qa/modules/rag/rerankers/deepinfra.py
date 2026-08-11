"""DeepInfra reranker backend."""
from __future__ import annotations

from typing import Sequence

from finance_qa.modules.rag.deepinfra_client import (
    INFERENCE_URL,
    DeepInfraClient,
    DeepInfraError,
    api_key,
)


RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"


def rerank(
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
    data = (client or DeepInfraClient(key=key)).post(f"{INFERENCE_URL}/{model}", payload)
    scores = data.get("scores")
    if scores is None or len(scores) != len(documents):
        raise DeepInfraError(
            f"reranker returned {None if scores is None else len(scores)} scores "
            f"for {len(documents)} documents: {str(data)[:200]}"
        )
    return [float(score) for score in scores]


class DeepInfraReranker:
    """`RerankerClient` over the DeepInfra inference route."""

    def __init__(self, model: str = RERANK_MODEL, *, client: DeepInfraClient | None = None) -> None:
        self.model = model
        self.name = model.rsplit("/", 1)[-1]
        self.client = client

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        return rerank(query, documents, model=self.model, client=self.client)
