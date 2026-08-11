"""Tests for the DeepInfra backends with the HTTP layer stubbed (no network, no key).

The API is deliberately never called: these must run offline, for free, and be
deterministic. What is checked is everything *around* the call: batching,
response-order handling, normalization, which errors retry and which do not, that
the registry hands back the right client, and that `CandidateRetriever` drives an
arbitrary `EmbeddingClient` / `RerankerClient` without changing pool membership.
Nothing here proves the models are good; it proves the plumbing is.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import numpy as np

from finance_qa.core.paths import QWEN3_INDEX_PATH
from finance_qa.modules.rag import deepinfra_client
from finance_qa.modules.rag.candidates import CandidateRetriever
from finance_qa.modules.rag.indexing import deepinfra
from finance_qa.modules.rag.retrievers.clients import (
    EMBEDDING_BACKENDS,
    embedding_client,
    rerank_order,
    reranker_client,
)
from finance_qa.modules.rag.rerankers import deepinfra as deepinfra_reranker


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


KEY = "test-key-not-a-real-one"
deepinfra_client.time.sleep = lambda _seconds: None  # backoff must not slow the tests


class Response(io.BytesIO):
    """Minimal stand-in for the urlopen context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def install(handler):
    """Route every deepinfra POST to `handler(url, payload)`; returns the call log."""
    calls: list[tuple[str, dict]] = []

    def urlopen(request, timeout=None):  # noqa: ARG001 - signature must match
        payload = json.loads(request.data)
        calls.append((request.full_url, payload))
        return Response(json.dumps(handler(request.full_url, payload)).encode())

    deepinfra_client.urllib.request.urlopen = urlopen
    return calls


def http_error(code: int, body: str):
    def raise_it(url, payload):  # noqa: ARG001
        raise urllib.error.HTTPError(url, code, "boom", {}, io.BytesIO(body.encode()))

    return raise_it


# -- embeddings -------------------------------------------------------------

# Deliberately out of order and unnormalized: the API promises neither.
def embed_handler(url, payload):
    data = [
        {"index": i, "embedding": [float(len(text)), 0.0, 3.0]}
        for i, text in enumerate(payload["input"])
    ]
    return {"data": list(reversed(data))}


calls = install(embed_handler)
vectors = deepinfra.embed(["aa", "bbbb", "c"], batch=2, key=KEY)
check("one request per batch", len(calls) == 2)
check("batches are sized as asked", [len(c[1]["input"]) for c in calls] == [2, 1])
check("embeddings hit the OpenAI-compatible route", calls[0][0] == deepinfra.EMBED_URL)
check("output is fp16", vectors.dtype == np.float16)
check("output shape is [n, dim]", vectors.shape == (3, 3))
check("rows are L2-normalized", np.allclose(np.linalg.norm(vectors.astype(np.float32), axis=1), 1.0, atol=1e-3))
# Row 0 came back last in the response; `index` is what must decide its place.
check(
    "rows follow the response index, not arrival order",
    vectors[0][0] < vectors[1][0] and vectors[2][0] < vectors[0][0],
)

calls = install(embed_handler)
deepinfra.embed(["", "   ", "x"], key=KEY)
check("empty text is sent as a space, never as ''", calls[0][1]["input"] == [" ", " ", "x"])

calls = install(embed_handler)
deepinfra.embed_queries(["Tổng tài sản?"], key=KEY)
check(
    "queries carry the Qwen3 task instruction",
    calls[0][1]["input"][0] == deepinfra.QUERY_INSTRUCTION + "Tổng tài sản?",
)
calls = install(embed_handler)
deepinfra.embed(["Tổng tài sản?"], key=KEY)
check("documents are embedded bare", calls[0][1]["input"][0] == "Tổng tài sản?")

calls = install(embed_handler)
deepinfra.embed(["a"], model="some/other-model", key=KEY)
check("model is overridable", calls[0][1]["model"] == "some/other-model")
check("the default embed model is Qwen3-Embedding-4B", deepinfra.EMBED_MODEL == "Qwen/Qwen3-Embedding-4B")

install(lambda url, payload: {"data": [{"index": 0, "embedding": [1.0]}]})
try:
    deepinfra.embed(["a", "b"], key=KEY)
    short_batch_accepted = True
except deepinfra.DeepInfraError:
    short_batch_accepted = False
check("a short batch is an error, not a silent row shift", not short_batch_accepted)

try:
    deepinfra.embed([], key=KEY)
    empty_accepted = True
except ValueError:
    empty_accepted = False
check("embedding nothing is a caller bug", not empty_accepted)


# -- retry policy -----------------------------------------------------------

calls = install(http_error(402, "You need positive balance to do inference"))
try:
    deepinfra.embed(["a"], key=KEY)
    balance_error = ""
except deepinfra.DeepInfraError as exc:
    balance_error = str(exc)
check("402 is surfaced, not swallowed", "402" in balance_error)
check("402 carries the API's own explanation", "positive balance" in balance_error)
check("402 is not retried", len(calls) == 1)

calls = install(http_error(401, "bad key"))
try:
    deepinfra.embed(["a"], key=KEY)
except deepinfra.DeepInfraError:
    pass
check("401 is not retried either", len(calls) == 1)

calls = install(http_error(503, "upstream busy"))
try:
    deepinfra.embed(["a"], key=KEY)
except deepinfra.DeepInfraError:
    pass
check("5xx is retried to the limit", len(calls) == deepinfra.RETRIES)

calls = install(http_error(429, "slow down"))
try:
    deepinfra.embed(["a"], key=KEY)
except deepinfra.DeepInfraError:
    pass
check("429 is retried (rate limits do recover)", len(calls) == deepinfra.RETRIES)

attempts: list[int] = []


def flaky(url, payload):  # noqa: ARG001
    attempts.append(1)
    if len(attempts) < 3:
        raise urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(b"{}"))
    return {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}


install(flaky)
recovered = deepinfra.embed(["a"], key=KEY)
check("a transient failure recovers within the retry budget", recovered.shape == (1, 2))

deepinfra_client.os.environ["DEEPINFRA_API_KEY"] = " env-key "
check("api_key comes from the environment, stripped", deepinfra.api_key() == "env-key")


# -- reranker ---------------------------------------------------------------

def rerank_handler(url, payload):  # noqa: ARG001
    return {"scores": [float(len(d)) for d in payload["documents"]]}


calls = install(rerank_handler)
scores = deepinfra_reranker.rerank("q", ["aaa", "b"], key=KEY)
check("rerank uses the inference route for the model", calls[0][0].endswith(deepinfra_reranker.RERANK_MODEL))
check("the default reranker is Qwen3-Reranker-0.6B", deepinfra_reranker.RERANK_MODEL == "Qwen/Qwen3-Reranker-0.6B")
check("the query is paired with every document", calls[0][1]["queries"] == ["q", "q"])
check("scores come back per document, in input order", scores == [3.0, 1.0])
check("no request is made for an empty document list", deepinfra_reranker.rerank("q", [], key=KEY) == [])

install(rerank_handler)
check("empty documents are sent as a space here too", deepinfra_reranker.rerank("q", [""], key=KEY) == [1.0])

install(lambda url, payload: {"scores": [1.0]})
try:
    deepinfra_reranker.rerank("q", ["a", "b"], key=KEY)
    mismatch_accepted = True
except deepinfra.DeepInfraError:
    mismatch_accepted = False
check("a score/document count mismatch is an error", not mismatch_accepted)

install(lambda url, payload: {"error": "nope"})
try:
    deepinfra_reranker.rerank("q", ["a"], key=KEY)
    missing_scores_accepted = True
except deepinfra.DeepInfraError:
    missing_scores_accepted = False
check("a response without scores is an error", not missing_scores_accepted)

# `rerank_order` is shared by every backend, so it is tested against the hosted
# client here and against a hand-written one below -- same function, both times.
hosted_reranker = deepinfra_reranker.DeepInfraReranker()

install(rerank_handler)
check(
    "rerank_order sorts by score, best first",
    rerank_order(hosted_reranker, "q", ["k1", "k2", "k3"], ["b", "aaa", "cc"]) == ["k2", "k3", "k1"],
)
install(lambda url, payload: {"scores": [1.0] * len(payload["documents"])})
check(
    "ties keep the incoming order",
    rerank_order(hosted_reranker, "q", ["k1", "k2", "k3"], ["a", "b", "c"]) == ["k1", "k2", "k3"],
)
try:
    rerank_order(hosted_reranker, "q", ["k1"], ["a", "b"])
    misaligned_accepted = True
except ValueError:
    misaligned_accepted = False
check("keys and texts must line up", not misaligned_accepted)


class LyingReranker:
    """Returns the wrong number of scores -- a backend bug must not shift keys."""

    name = "lying"

    def scores(self, query, documents):  # noqa: ARG002
        return [1.0]


try:
    rerank_order(LyingReranker(), "q", ["k1", "k2"], ["a", "b"])
    lie_accepted = True
except ValueError:
    lie_accepted = False
check("a backend returning too few scores is an error", not lie_accepted)
check("no scoring call is made for an empty pool", rerank_order(LyingReranker(), "q", [], []) == [])


# -- wiring into the retriever ---------------------------------------------

REPORT = "AAA_financial_statements_2020_consolidated"
TABLES = [
    {
        "report_id": REPORT, "table_pos": pos, "ticker": "AAA", "year": 2020,
        "doc_type": "consolidated", "company_name": "CTCP Alpha",
        "statement_type": stype,
        # `filters.has_content` reads both; these describe an ordinary table.
        "num_rows": 20, "first_col_labels": ["Tài sản"],
    }
    for pos, stype in [(1, "note"), (2, "note"), (3, "balance_sheet")]
]
DOC_TEXTS = {
    f"{REPORT}|1": "thuyết minh tổng tài sản chi tiết tài sản",
    f"{REPORT}|2": "thuyết minh tài sản cố định tổng",
    f"{REPORT}|3": "bảng cân đối kế toán",
}
QUESTION = {
    "question": "Tổng tài sản năm 2020 của CTCP Alpha (AAA) là bao nhiêu?",
    "tickers": ["AAA"],
    "years": [2020],
    "doc_type": "consolidated",
}

plain = CandidateRetriever(
    use_dense=False, channel_k=2, tables=TABLES, doc_texts=DOC_TEXTS
).build_pool(QUESTION)
check("baseline pool is bm25 order plus the rescued balance sheet", plain.ranked == [f"{REPORT}|{i}" for i in (1, 2, 3)])

seen: list[tuple[str, list[str]]] = []


class FakeReranker:
    """A `RerankerClient` that is not DeepInfra -- the point of the protocol."""

    name = "fake"

    def scores(self, query, documents):
        seen.append((query, list(documents)))
        # Invert the fused order, so a no-op would be visible as a pass.
        return [float(i) for i in range(len(documents))]


reranked = CandidateRetriever(
    use_dense=False, channel_k=2, reranker=FakeReranker(), tables=TABLES, doc_texts=DOC_TEXTS
).build_pool(QUESTION)
check("the reranker reorders the pool", reranked.ranked == list(reversed(plain.ranked)))
check("pool membership is unchanged by reranking", set(reranked.ranked) == set(plain.ranked))
check("the pre-rerank order is kept for diagnosis", reranked.rankings["fused"] == plain.ranked)
check("the reranker scores the whole pool", len(seen) == 1 and len(seen[0][1]) == 3)
check("the reranker reads the original question, not the stripped query", seen[0][0] == QUESTION["question"])
check("the stripped query is still what bm25 saw", reranked.query == plain.query)
check("the reranker reads doc_text", seen[0][1][0] == DOC_TEXTS[f"{REPORT}|1"])

empty = CandidateRetriever(
    use_dense=False, channel_k=2, reranker=FakeReranker(), tables=TABLES, doc_texts=DOC_TEXTS
).build_pool({**QUESTION, "tickers": ["ZZZ"]})
check("a question with no candidates yields an empty pool", empty.ranked == [])
check("an empty pool is not sent to the reranker", len(seen) == 1)

try:
    CandidateRetriever(
        use_dense=False, use_bm25=False, reranker=FakeReranker(), tables=TABLES, doc_texts={}
    )
    reranker_without_text = True
except ValueError:
    reranker_without_text = False
check("the reranker without doc_text fails at construction", not reranker_without_text)

try:
    CandidateRetriever(use_dense=False, dense_backend="qwen3-72b", tables=TABLES, doc_texts=DOC_TEXTS)
    unknown_backend = True
except ValueError:
    unknown_backend = False
check("an unknown dense_backend is rejected", not unknown_backend)

try:
    CandidateRetriever(use_dense=False, reranker="bge-reranker", tables=TABLES, doc_texts=DOC_TEXTS)
    unknown_reranker = True
except ValueError:
    unknown_reranker = False
check("an unknown reranker name is rejected", not unknown_reranker)


# -- the registries ---------------------------------------------------------

check(
    "the qwen3-4b client is a DeepInfra embedder",
    isinstance(embedding_client("qwen3-4b"), deepinfra.DeepInfraEmbedder),
)
check(
    "the qwen3-0.6b client is a DeepInfra reranker",
    isinstance(reranker_client("qwen3-0.6b"), deepinfra_reranker.DeepInfraReranker),
)
# bge-m3's index cannot be rebuilt, so a second backend sharing its path would be
# unrecoverable: distinct index files is a data-safety check, not a style one.
check("each embedding backend owns a distinct index file", len({
    embedding_client(name).index_path for name in EMBEDDING_BACKENDS
}) == len(EMBEDDING_BACKENDS))

qwen = deepinfra.DeepInfraEmbedder()
check("the embedder points at the qwen3 index, not the bge-m3 one", qwen.index_path == QWEN3_INDEX_PATH)
calls = install(embed_handler)
qwen.embed_queries(["tài sản"])
check("embed_queries goes through the client", calls[0][1]["input"][0].startswith("Instruct:"))
calls = install(embed_handler)
qwen.embed_documents(["tài sản"])
check("embed_documents goes through the client bare", calls[0][1]["input"] == ["tài sản"])

install(rerank_handler)
check("the DeepInfra reranker satisfies the protocol", deepinfra_reranker.DeepInfraReranker().scores("q", ["aaa"]) == [3.0])

# A retriever driven entirely by injected clients: the swap the protocol exists for.
encoded: list[list[str]] = []


class FakeEmbedder:
    name = "fake"
    index_path = Path("/nonexistent/fake.npy")

    def embed_documents(self, texts):
        return np.zeros((len(texts), 4), dtype=np.float16)

    def embed_queries(self, texts):
        encoded.append(list(texts))
        return np.zeros((len(texts), 4), dtype=np.float16)


injected = CandidateRetriever(
    use_dense=False, dense_backend=FakeEmbedder(), tables=TABLES, doc_texts=DOC_TEXTS
)
injected._encode(["tài sản"])
check("an injected embedder needs no registry entry", encoded == [["tài sản"]])

print("tất cả PASS")
