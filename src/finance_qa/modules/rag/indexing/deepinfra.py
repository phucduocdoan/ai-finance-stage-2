"""DeepInfra embedding backend for the dense retrieval channel."""
from __future__ import annotations

from typing import Sequence

from finance_qa.core.paths import QWEN3_INDEX_PATH
from finance_qa.modules.rag.deepinfra_client import (
    EMBED_URL,
    RETRIES,
    TIMEOUT,
    DeepInfraClient,
    DeepInfraError,
    api_key,
)


EMBED_MODEL = "Qwen/Qwen3-Embedding-4B"

QUERY_INSTRUCTION = (
    "Instruct: Given a financial question in Vietnamese, retrieve the table that "
    "contains the figure needed to answer it\nQuery: "
)

EMBED_BATCH = 64


def embed(
    texts: Sequence[str],
    *,
    model: str = EMBED_MODEL,
    batch: int = EMBED_BATCH,
    key: str | None = None,
    client: DeepInfraClient | None = None,
):
    """Embed documents. Returns fp16 [n, dim], L2-normalized, in input order."""
    import numpy as np

    if not texts:
        raise ValueError("embed() needs at least one text")
    http = client or DeepInfraClient(key=key)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        chunk = list(texts[start : start + batch])
        payload = {"model": model, "input": [text if text.strip() else " " for text in chunk]}
        data = http.post(EMBED_URL, payload)["data"]
        if len(data) != len(chunk):
            raise DeepInfraError(f"asked for {len(chunk)} embeddings, got {len(data)}")
        for row in sorted(data, key=lambda item: item["index"]):
            vectors.append(row["embedding"])
    out = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return (out / np.maximum(norms, 1e-12)).astype(np.float16)


def embed_queries(texts: Sequence[str], **kwargs):
    """Embed questions with the retrieval instruction Qwen3 expects."""
    return embed([QUERY_INSTRUCTION + text for text in texts], **kwargs)


class DeepInfraEmbedder:
    """`EmbeddingClient` over the DeepInfra embeddings route."""

    def __init__(
        self,
        model: str = EMBED_MODEL,
        *,
        index_path=QWEN3_INDEX_PATH,
        client: DeepInfraClient | None = None,
    ) -> None:
        self.model = model
        self.name = model.rsplit("/", 1)[-1]
        self.index_path = index_path
        # This index was built over doc_text. `dense_text` measured better for bge-m3, but
        # rebuilding a hosted index costs money, so the win is not inherited by assumption.
        self.text_column = "doc_text"
        self.client = client

    def embed_documents(self, texts: Sequence[str]):
        return embed(texts, model=self.model, client=self.client)

    def embed_queries(self, texts: Sequence[str]):
        return embed_queries(texts, model=self.model, client=self.client)
