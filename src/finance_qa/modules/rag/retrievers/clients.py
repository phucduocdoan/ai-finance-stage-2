"""Backend interfaces for the dense channel and the reranker.

`CandidateRetriever` talks to these two protocols and to nothing model-specific,
so swapping bge-m3 for a hosted encoder, or DeepInfra for a local vLLM or an
Alibaba endpoint, is a new class in one file plus a registry line -- no change to
pool assembly, the judge, or the runner.

An embedding client owns *all three* parts of its channel: the encoder, the text
column it read, and the index file it produced. None of them can be mixed -- a
query vector only means something against vectors from the same encoder over the
same text -- so `index_path` and `text_column` are properties of the client
rather than separate arguments the caller could get wrong.

`text_column` exists because BM25 and a dense encoder do not want the same text.
An unmatched token is free for BM25 and not for a bi-encoder, which has no IDF to
discount it with; measured, that is worth top-3 +7 over 154 gold questions
*with the reranker off* (docs/retrieval_preprocessing_2026-08-21.md §10.3-10.4).
With the production reranker it is not: a rerank replaces the fused order, so only
pool membership survives, the two tie at top-20, and end to end through `_evidence`
the DOCS tier is identical while TABLES stays inside the run-to-run churn floor
(§10.5-10.6). Hence `bge-m3` is still the default backend and this one is opt-in.

A reranker client only has to score query/document pairs. Ordering, tie-breaking
and the empty case are `rerank_order`'s job here, so every backend gets the same
behaviour for free.
"""

from __future__ import annotations

import asyncio
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
    text_column: str

    def embed_documents(self, texts: Sequence[str]):
        """fp16 [n, dim], L2-normalized, in input order."""

    def embed_queries(self, texts: Sequence[str]):
        """Same contract as `embed_documents`, for question text."""


class RerankerClient(Protocol):
    """A cross-encoder over (query, document) pairs.

    `scores` is the only required method. A hosted backend should also offer
    `async def ascores(...)` so `arerank_order` can await it on the event loop
    instead of parking a thread on a network round trip; an in-process model
    backend has nothing to gain from that, and `arerank_order` runs its `scores`
    in a thread, which is where CPU/GPU work belongs anyway.
    """

    name: str

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        """Relevance per document, in input order. Higher is more relevant."""


# Registries. Lazily imported so that asking for a hosted backend does not pull
# torch onto a machine that is only making HTTP calls, and vice versa.
EMBEDDING_BACKENDS = ("bge-m3", "bge-m3-dense-text", "qwen3-4b")
RERANKER_BACKENDS = ("qwen3-0.6b",)


def embedding_client(name: str) -> EmbeddingClient:
    if name == "bge-m3":
        from finance_qa.modules.rag.indexing.dense import BgeM3Embedder

        return BgeM3Embedder()
    if name == "bge-m3-dense-text":
        from finance_qa.modules.rag.indexing.dense import BgeM3DenseTextEmbedder

        return BgeM3DenseTextEmbedder()
    if name == "qwen3-4b":
        from finance_qa.modules.rag.indexing.deepinfra import DeepInfraEmbedder

        return DeepInfraEmbedder()
    raise ValueError(
        f"unknown embedding backend {name!r}; expected one of {list(EMBEDDING_BACKENDS)}"
    )


def reranker_client(name: str) -> RerankerClient:
    if name == "qwen3-0.6b":
        from finance_qa.modules.rag.rerankers.deepinfra import DeepInfraReranker

        return DeepInfraReranker()
    raise ValueError(
        f"unknown reranker backend {name!r}; expected one of {list(RERANKER_BACKENDS)}"
    )


def _ordered(
    client: RerankerClient, keys: Sequence[str], scores: Sequence[float]
) -> list[str]:
    if len(scores) != len(keys):
        raise ValueError(f"{client.name} returned {len(scores)} scores for {len(keys)} keys")
    return [keys[i] for i in sorted(range(len(keys)), key=lambda i: (-scores[i], i))]


def _checked(keys: Sequence[str], texts: Sequence[str]) -> bool:
    """True if there is anything to score. Raises on a caller misalignment."""
    if len(keys) != len(texts):
        raise ValueError(f"{len(keys)} keys but {len(texts)} texts")
    return bool(keys)


async def arerank_order(
    client: RerankerClient,
    query: str,
    keys: Sequence[str],
    texts: Sequence[str],
) -> list[str]:
    """Keys sorted by score, best first; ties keep the incoming order."""
    if not _checked(keys, texts):
        return []
    ascores = getattr(client, "ascores", None)
    if ascores is None:
        scores = await asyncio.to_thread(client.scores, query, texts)
    else:
        scores = await ascores(query, texts)
    return _ordered(client, keys, scores)


def rerank_order(
    client: RerankerClient,
    query: str,
    keys: Sequence[str],
    texts: Sequence[str],
) -> list[str]:
    """Sync `arerank_order`, for the offline probes and the pool unit tests."""
    if not _checked(keys, texts):
        return []
    return _ordered(client, keys, client.scores(query, texts))
