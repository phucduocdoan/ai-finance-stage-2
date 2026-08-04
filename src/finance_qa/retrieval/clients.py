"""Backend interfaces for the dense channel and the reranker.

`CandidateRetriever` talks to these two protocols and to nothing model-specific,
so swapping bge-m3 for a hosted encoder, or DeepInfra for a local vLLM or an
Alibaba endpoint, is a new class in one file plus a registry line -- no change to
pool assembly, the judge, or the runner.

An embedding client owns *both* halves of its channel: the encoder and the index
file it produced. They cannot be mixed (a query vector only means something
against vectors from the same encoder), so `index_path` is a property of the
client rather than a separate argument the caller could get wrong.

A reranker client only has to score query/document pairs. Ordering, tie-breaking
and the empty case are `rerank_order`'s job here, so every backend gets the same
behaviour for free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence


class EmbeddingClient(Protocol):
    """A dense channel: an encoder plus the index it built.

    Documents and queries are separate methods because asymmetric models exist
    (Qwen3 wants a task instruction on the query, bge-m3 wants nothing). A flag
    would let a caller silently embed a query as a document.
    """

    name: str
    index_path: Path

    def embed_documents(self, texts: Sequence[str]):
        """fp16 [n, dim], L2-normalized, in input order."""

    def embed_queries(self, texts: Sequence[str]):
        """Same contract as `embed_documents`, for question text."""


class RerankerClient(Protocol):
    """A cross-encoder over (query, document) pairs."""

    name: str

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        """Relevance per document, in input order. Higher is more relevant."""


# Registries. Lazily imported so that asking for a hosted backend does not pull
# torch onto a machine that is only making HTTP calls, and vice versa.
EMBEDDING_BACKENDS = ("bge-m3", "qwen3-4b")
RERANKER_BACKENDS = ("qwen3-0.6b",)


def embedding_client(name: str) -> EmbeddingClient:
    if name == "bge-m3":
        from finance_qa.retrieval.dense import BgeM3Embedder

        return BgeM3Embedder()
    if name == "qwen3-4b":
        from finance_qa.retrieval.deepinfra import DeepInfraEmbedder

        return DeepInfraEmbedder()
    raise ValueError(
        f"unknown embedding backend {name!r}; expected one of {list(EMBEDDING_BACKENDS)}"
    )


def reranker_client(name: str) -> RerankerClient:
    if name == "qwen3-0.6b":
        from finance_qa.retrieval.deepinfra import DeepInfraReranker

        return DeepInfraReranker()
    raise ValueError(
        f"unknown reranker backend {name!r}; expected one of {list(RERANKER_BACKENDS)}"
    )


def rerank_order(
    client: RerankerClient,
    query: str,
    keys: Sequence[str],
    texts: Sequence[str],
) -> list[str]:
    """Keys sorted by score, best first; ties keep the incoming order."""
    if len(keys) != len(texts):
        raise ValueError(f"{len(keys)} keys but {len(texts)} texts")
    if not keys:
        return []
    scores = client.scores(query, texts)
    if len(scores) != len(keys):
        raise ValueError(f"{client.name} returned {len(scores)} scores for {len(keys)} keys")
    return [keys[i] for i in sorted(range(len(keys)), key=lambda i: (-scores[i], i))]
