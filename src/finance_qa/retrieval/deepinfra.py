"""DeepInfra-hosted embedding and reranking.

Implements `retrieval.clients.EmbeddingClient` / `RerankerClient`, so this module
is the only place that knows DeepInfra exists; the retriever sees the protocols.

Why hosted models at all, when bge-m3 already runs locally: the local GPU is
shared with unrelated services (78 of 81 GiB in use when measured), so a bigger
encoder cannot be loaded alongside it, and the dense index it produced cannot be
rebuilt at all — metadata v1 is gone. Putting the second encoder behind an HTTP
call keeps both facts true at once.

Two models, two different jobs:

- `Qwen/Qwen3-Embedding-4B` replaces the bge-m3 *channel*: it needs all 146,246
  table texts embedded once, into its own index file.
- `Qwen/Qwen3-Reranker-0.6B` runs *per question* over the fused pool only
  (~60-130 candidates), so it needs no index and can be switched on immediately.

The reranker is the cheaper experiment by three orders of magnitude, and it
targets the measured bottleneck: with ground-truth tables the planner scores
15/15, but the pool only carries the full ground-truth set for 8 of 15 questions,
so pool *ordering* is what caps end-to-end accuracy.

Credentials: `DEEPINFRA_API_KEY` from the environment, falling back to the repo
`.env`. Never logged, and no default is invented if it is missing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Sequence

from finance_qa.paths import PROJECT_ROOT, QWEN3_INDEX_PATH


BASE_URL = "https://api.deepinfra.com"
EMBED_URL = f"{BASE_URL}/v1/openai/embeddings"
INFERENCE_URL = f"{BASE_URL}/v1/inference"

EMBED_MODEL = "Qwen/Qwen3-Embedding-4B"
RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"

# Qwen3 embedding is asymmetric: documents are embedded bare, queries carry a
# task instruction. Using the same text for both measurably costs recall, so the
# two entry points are deliberately separate functions rather than one flag.
QUERY_INSTRUCTION = (
    "Instruct: Given a financial question in Vietnamese, retrieve the table that "
    "contains the figure needed to answer it\nQuery: "
)

EMBED_BATCH = 64
TIMEOUT = 120
RETRIES = 4


class DeepInfraError(RuntimeError):
    """An API call that retrying will not fix (bad key, no balance, bad model)."""


def api_key() -> str:
    key = os.environ.get("DEEPINFRA_API_KEY", "").strip()
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "DEEPINFRA_API_KEY" and value.strip():
                return value.strip()
    raise DeepInfraError("DEEPINFRA_API_KEY is not set (environment or .env)")


def _post(url: str, payload: dict, *, key: str | None = None) -> dict:
    """POST JSON with backoff. 4xx is terminal; 5xx and transport errors retry."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key or api_key()}",
        "Content-Type": "application/json",
    }
    last = ""
    for attempt in range(RETRIES):
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            # 402 (no balance), 401 (bad key) and 404 (bad model) never recover by
            # retrying, and hammering a billing error is what gets a key blocked.
            if exc.code < 500 and exc.code != 429:
                raise DeepInfraError(f"HTTP {exc.code} from {url}: {detail}") from exc
            last = f"HTTP {exc.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < RETRIES - 1:
            time.sleep(2**attempt)
    raise DeepInfraError(f"{url} failed after {RETRIES} attempts: {last}")


def embed(
    texts: Sequence[str],
    *,
    model: str = EMBED_MODEL,
    batch: int = EMBED_BATCH,
    key: str | None = None,
):
    """Embed documents. Returns fp16 [n, dim], L2-normalized, in input order.

    fp16 and L2 normalization match `retrieval.dense`, so a cosine ranking is the
    same matmul on either index and the two backends stay swappable.
    """
    import numpy as np

    if not texts:
        raise ValueError("embed() needs at least one text")
    key = key or api_key()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        chunk = list(texts[start : start + batch])
        # The API rejects empty strings; 0-length judge_text exists in the corpus.
        payload = {"model": model, "input": [t if t.strip() else " " for t in chunk]}
        data = _post(EMBED_URL, payload, key=key)["data"]
        if len(data) != len(chunk):
            raise DeepInfraError(f"asked for {len(chunk)} embeddings, got {len(data)}")
        # Order is not promised by the response, only by `index`.
        for row in sorted(data, key=lambda r: r["index"]):
            vectors.append(row["embedding"])
    out = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return (out / np.maximum(norms, 1e-12)).astype(np.float16)


def embed_queries(texts: Sequence[str], **kwargs):
    """Embed questions with the retrieval instruction Qwen3 expects."""
    return embed([QUERY_INSTRUCTION + t for t in texts], **kwargs)


def rerank(
    query: str,
    documents: Sequence[str],
    *,
    model: str = RERANK_MODEL,
    key: str | None = None,
) -> list[float]:
    """Relevance score per document, in input order. Higher is more relevant."""
    if not documents:
        return []
    payload = {
        "queries": [query] * len(documents),
        "documents": [d if d.strip() else " " for d in documents],
    }
    data = _post(f"{INFERENCE_URL}/{model}", payload, key=key)
    scores = data.get("scores")
    if scores is None or len(scores) != len(documents):
        raise DeepInfraError(
            f"reranker returned {None if scores is None else len(scores)} scores "
            f"for {len(documents)} documents: {str(data)[:200]}"
        )
    return [float(s) for s in scores]


class DeepInfraEmbedder:
    """`EmbeddingClient` over the OpenAI-compatible embeddings route."""

    def __init__(self, model: str = EMBED_MODEL, *, index_path=QWEN3_INDEX_PATH) -> None:
        self.model = model
        self.name = model.rsplit("/", 1)[-1]
        self.index_path = index_path

    def embed_documents(self, texts: Sequence[str]):
        return embed(texts, model=self.model)

    def embed_queries(self, texts: Sequence[str]):
        return embed_queries(texts, model=self.model)


class DeepInfraReranker:
    """`RerankerClient` over the DeepInfra inference route."""

    def __init__(self, model: str = RERANK_MODEL) -> None:
        self.model = model
        self.name = model.rsplit("/", 1)[-1]

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        return rerank(query, documents, model=self.model)
