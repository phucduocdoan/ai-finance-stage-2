"""Candidate-pool assembly: hard filter -> BM25 + dense -> RRF -> pool -> judge.

This is the single implementation of the retrieval pool. Both the evaluator
(`finance_qa.evaluation.retrieval`) and the batch runner go through it, so a
policy measured on the eval set is the policy production runs. Before this
module existed the good policies lived in `scripts/dump_pools.py` and the
evaluator quietly ran without them; see docs/HANDOFF.md §4.

Three policies are on by default because each was measured on the 15 table-GT
questions (docs/v0_retrieval_pipeline.md):

1. **stripped retrieval query** -- the hard filter has already spent ticker,
   year and scope, so those tokens in the query only boost the entity_info
   tables that repeat the company name verbatim (pool recall 92.0% -> 97.1%).
   Only the *retrieval* query is stripped; the judge still reads the original
   question, which needs the year to pick per-year tables.
2. **primary-statement expansion** -- every `balance_sheet` /
   `income_statement` / `cash_flow` / `equity_change` table in the shortlist
   joins the pool unconditionally. Primary statements are ~10% of a report's
   tables and lose the lexical fight to the notes, so a balance-sheet question
   ranks its own GT out of the pool (97.1% -> 100.0%).
3. **judge_text** -- the judge reads the narrow per-table view (no boilerplate
   section_title, no period-column header): 22% fewer chars, no loss of signal.
   The dense index and BM25 keep the wide `doc_text` they were built on.

The dense channel and the optional reranker are backends, not hardcoded models:
they are `retrieval.clients.EmbeddingClient` / `RerankerClient`, passed either as
a registry name (`dense_backend="qwen3-4b"`, `reranker="qwen3-0.6b"`) or as an
instance. Nothing below knows which vendor is answering. Defaults stay bge-m3 and
no reranker because those are the only measured settings.

The pure functions here take plain data and no IO, which is what the unit tests
exercise. `CandidateRetriever` owns the expensive artifacts (146k-row metadata,
BM25 IDF, dense index, bge-m3 on GPU) and is what callers construct.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from finance_qa.paths import DOCUMENT_TEXT_PATH
from finance_qa.retrieval.bm25 import BM25
from finance_qa.retrieval.clients import (
    EMBEDDING_BACKENDS,
    RERANKER_BACKENDS,
    EmbeddingClient,
    RerankerClient,
    embedding_client,
    rerank_order,
    reranker_client,
)
from finance_qa.retrieval.filters import index_by_ticker_year, load_tables, shortlist
from finance_qa.retrieval.judge import judge as judge_pool_llm


# Per-channel depth before fusion. Q7 specified 50; measured down to 20 because
# the pool is a *union* of two rankings, so channel depth buys pool size much
# faster than it buys recall: 50 -> 20 shrinks the pool from med 78 / max 131 to
# med 38 / max 97 with union all-hit@20 unchanged at 93.3% (flat from k=15 up).
# The judge reads the whole pool, so this is the knob that sets its bill.
CHANNEL_K = 20
RRF_K = 60

PRIMARY_STATEMENT_TYPES = frozenset(
    {"balance_sheet", "income_statement", "cash_flow", "equity_change"}
)

# Generic corporate boilerplate. Every Vietnamese issuer name is built out of
# these, so they match the entity_info tables in every single report.
BOILERPLATE = frozenset({
    "công", "ty", "cổ", "phần", "ctcp", "tập", "đoàn", "tổng", "ngân", "hàng",
    "tmcp", "thương", "mại", "tnhh", "một", "thành", "viên", "việt", "nam",
    "của", "là", "bao", "nhiêu", "năm", "vào", "tại", "và", "cho", "các",
})

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_YEAR_RE = re.compile(r"(19|20)\d\d")


def table_key(table: Mapping) -> str:
    """`report_id|table_pos`, the id used everywhere downstream."""
    return f"{table['report_id']}|{table['table_pos']}"


def company_name_tokens(tables: Iterable[Mapping]) -> dict[str, set[str]]:
    """ticker -> the word tokens of that issuer's name, for query stripping."""
    names: dict[str, set[str]] = defaultdict(set)
    for table in tables:
        for token in _WORD_RE.findall((table.get("company_name") or "").lower()):
            names[table["ticker"]].add(token)
    return names


def strip_entity(question: str, ticker_names: set[str]) -> str:
    """Drop tokens the hard filter already spent: years, issuer name, boilerplate."""
    kept = []
    for token in _WORD_RE.findall(question.lower()):
        if _YEAR_RE.fullmatch(token):
            continue
        if token in ticker_names or token in BOILERPLATE:
            continue
        kept.append(token)
    return " ".join(kept)


def rrf_fuse(*rankings: Sequence[str], k: int = RRF_K) -> list[str]:
    """Reciprocal rank fusion. Ranks are 1-based; missing from a list = no term."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] += 1.0 / (k + rank)
    return sorted(scores, key=lambda key: -scores[key])


def add_primary_statements(
    ranked: Sequence[str],
    keys: Sequence[str],
    statement_types: Mapping[str, str],
) -> list[str]:
    """Append every shortlisted primary statement that ranking left out.

    Appended, not promoted: the ranking is still the best guess at relevance, and
    the judge reads the whole pool anyway. Shortlist order keeps it deterministic.
    """
    out = list(ranked)
    seen = set(out)
    out += [
        key for key in keys
        if key not in seen
        and statement_types.get(key) in PRIMARY_STATEMENT_TYPES
    ]
    return out


def assemble_pool(
    keys: Sequence[str],
    rankings: Sequence[Sequence[str]] = (),
    statement_types: Mapping[str, str] | None = None,
    *,
    expand_primary: bool = True,
    rrf_k: int = RRF_K,
) -> list[str]:
    """Shortlist + per-channel rankings -> the ordered candidate pool.

    Zero rankings means filter-only, where the shortlist order is all there is.
    One ranking is used as-is; two or more are RRF-fused.
    """
    rankings = [r for r in rankings if r is not None]
    if not rankings:
        ranked = list(keys)
    elif len(rankings) == 1:
        ranked = list(rankings[0])
    else:
        ranked = rrf_fuse(*rankings, k=rrf_k)
    if expand_primary and statement_types:
        ranked = add_primary_statements(ranked, keys, statement_types)
    return ranked


def rerank_with_picks(ranked: Sequence[str], picks: Sequence[str]) -> list[str]:
    """Judge picks first, unpicked remainder keeps retrieval order.

    Keeping the tail means a failed or empty judge degrades to the retrieval
    ranking instead of to nothing, and the deeper Ks still measure something.
    """
    chosen = set(picks)
    return list(picks) + [key for key in ranked if key not in chosen]


@dataclass
class Pool:
    """One question's candidate pool, plus the per-channel rankings behind it."""

    query: str
    keys: list[str]
    ranked: list[str]
    rankings: dict[str, list[str]] = field(default_factory=dict)


class CandidateRetriever:
    """Owns the retrieval artifacts and builds pools for enriched questions.

    Questions are the enriched dicts (`question`, `tickers`, `years`,
    `doc_type`); ids are the caller's business. Construct once and reuse -- the
    constructor reads 146k metadata rows, builds BM25 IDF, and optionally loads
    the dense index plus bge-m3 onto the GPU.
    """

    def __init__(
        self,
        *,
        channel_k: int = CHANNEL_K,
        use_bm25: bool = True,
        use_dense: bool = True,
        dense_backend: str | EmbeddingClient = "bge-m3",
        reranker: str | RerankerClient | None = None,
        judge_top_n: int | None = None,
        expand_primary: bool = True,
        strip_query: bool = True,
        load_judge_text: bool = False,
        tables: list[dict] | None = None,
        doc_texts: dict[str, str] | None = None,
        judge_texts: dict[str, str] | None = None,
    ) -> None:
        self.channel_k = channel_k
        self.expand_primary = expand_primary
        self.strip_query = strip_query

        # Names are validated now but resolved on first use: instantiating the
        # bge-m3 client imports torch, which a hosted-only run has no reason to pay.
        if isinstance(dense_backend, str) and dense_backend not in EMBEDDING_BACKENDS:
            raise ValueError(
                f"unknown dense_backend {dense_backend!r}; "
                f"expected one of {list(EMBEDDING_BACKENDS)}"
            )
        self.dense_backend = dense_backend
        self._embedder = None if isinstance(dense_backend, str) else dense_backend

        if isinstance(reranker, str) and reranker not in RERANKER_BACKENDS:
            raise ValueError(
                f"unknown reranker {reranker!r}; expected one of {list(RERANKER_BACKENDS)}"
            )
        self.reranker = reranker_client(reranker) if isinstance(reranker, str) else reranker

        # Narrowing the judge's input is only as good as the order doing the
        # narrowing: whatever falls outside top-N is unreachable, so the cut sets a
        # hard ceiling at recall@N of `pool.ranked`. Off by default -- the measured
        # policy feeds the judge the whole pool, because the fused order was not
        # trustworthy enough to cut on (docs/v0_retrieval_pipeline.md, "union > RRF").
        if judge_top_n is not None and judge_top_n < 1:
            raise ValueError(f"judge_top_n must be >= 1, got {judge_top_n}")
        self.judge_top_n = judge_top_n

        self.tables = load_tables() if tables is None else tables
        self.index = index_by_ticker_year(self.tables)
        self.statement_types = {
            table_key(t): t["statement_type"] for t in self.tables
        }
        self.name_tokens = company_name_tokens(self.tables)

        self.bm25: BM25 | None = None
        self.judge_texts: dict[str, str] = judge_texts or {}
        self._dense = None

        # One parquet read serves BM25, the judge view and the dense row order;
        # the columns are 100+ MB each, so only take what this run asked for.
        columns = []
        if (use_bm25 or self.reranker is not None) and doc_texts is None:
            columns.append("doc_text")
        if load_judge_text and judge_texts is None:
            columns.append("judge_text")
        meta = None
        if columns or (use_dense and doc_texts is None):
            import pandas as pd

            meta = pd.read_parquet(
                DOCUMENT_TEXT_PATH, columns=["report_id", "table_pos", *columns]
            )
            keys = (meta["report_id"] + "|" + meta["table_pos"].astype(str)).tolist()
            if "doc_text" in columns:
                doc_texts = dict(zip(keys, meta["doc_text"]))
            if "judge_text" in columns:
                self.judge_texts = dict(zip(keys, meta["judge_text"]))

        self.doc_texts: dict[str, str] = doc_texts or {}

        if use_bm25:
            if not self.doc_texts:
                raise ValueError("use_bm25 needs doc_texts or the doc_text parquet")
            self.bm25 = BM25(self.doc_texts)

        if self.reranker is not None and not self.doc_texts:
            raise ValueError("a reranker needs doc_texts or the doc_text parquet")

        if use_dense:
            if meta is None:
                raise ValueError("use_dense needs the doc_text parquet for row order")
            import numpy as np

            index_path = self.embedder.index_path
            if not index_path.exists():
                raise FileNotFoundError(
                    f"dense backend {self.embedder.name!r} needs {index_path}; "
                    "build it first (scripts/build_deepinfra_index.py for qwen3-4b)"
                )
            vectors = np.load(index_path)
            if len(vectors) != len(keys):
                raise ValueError(
                    f"{index_path.name} has {len(vectors):,} rows but the doc_text "
                    f"parquet has {len(keys):,}; the index is stale"
                )
            self._dense = (vectors, {key: i for i, key in enumerate(keys)})

    # -- queries -----------------------------------------------------------

    @property
    def embedder(self) -> EmbeddingClient:
        if self._embedder is None:
            self._embedder = embedding_client(self.dense_backend)
        return self._embedder

    def query_for(self, question: Mapping) -> str:
        """The retrieval query, which is not the question the judge reads."""
        text = question["question"]
        if not self.strip_query:
            return text
        tickers = question.get("tickers") or []
        names: set[str] = set()
        for ticker in tickers:
            names |= self.name_tokens.get(ticker, set())
        return strip_entity(text, names)

    def _encode(self, queries: Sequence[str]):
        return self.embedder.embed_queries(list(queries))

    # -- pools -------------------------------------------------------------

    def build_pools(self, questions: Sequence[Mapping]) -> list[Pool]:
        """Pools for a batch of questions; queries are encoded in one GPU pass."""
        queries = [self.query_for(q) for q in questions]
        qvecs = self._encode(queries) if self._dense is not None else None
        return [
            self._build_pool(q, queries[i], None if qvecs is None else qvecs[i])
            for i, q in enumerate(questions)
        ]

    def build_pool(self, question: Mapping) -> Pool:
        return self.build_pools([question])[0]

    def _build_pool(self, question: Mapping, query: str, qvec) -> Pool:
        cands = shortlist(question, self.index, all_tables=self.tables)
        keys = [table_key(t) for t in cands]

        rankings: dict[str, list[str]] = {}
        if keys and self.bm25 is not None:
            rankings["bm25"] = [
                key for key, _ in self.bm25.top_k(query, keys, k=self.channel_k)
            ]
        if keys and qvec is not None:
            import numpy as np

            vecs, row_of = self._dense
            rows = np.array([row_of[key] for key in keys])
            sims = vecs[rows].astype(np.float32) @ qvec.astype(np.float32)
            order = np.argsort(-sims)[: self.channel_k]
            rankings["dense"] = [keys[i] for i in order]

        ranked = assemble_pool(
            keys,
            list(rankings.values()),
            self.statement_types,
            expand_primary=self.expand_primary,
        )

        if self.reranker is not None and ranked:
            # Keep the fused order so a rerank can be diagnosed against what it
            # replaced -- pool membership is unchanged, only the order moves.
            rankings["fused"] = list(ranked)
            # The original question, not the stripped query: the cross-encoder is
            # not behind a hard filter, so it needs the year and the entity that
            # `query_for` removed -- same reason the judge reads the original.
            ranked = rerank_order(
                self.reranker,
                question["question"],
                ranked,
                [self.doc_texts[key] for key in ranked],
            )

        return Pool(query=query, keys=keys, ranked=ranked, rankings=rankings)

    # -- judge -------------------------------------------------------------

    def judge_items(self, pool: Pool) -> list[tuple[str, str]]:
        """(key, judge_text) for what the judge is allowed to see, in pool order.

        With `judge_top_n` set this is the head of the pool, not all of it. The
        pool itself stays whole: `rerank_with_picks` still needs the tail, so a cut
        that turns out to be too aggressive costs judge recall but never loses a
        candidate from the ranking the deeper Ks measure.
        """
        if not self.judge_texts:
            raise RuntimeError("construct with load_judge_text=True to judge")
        keys = pool.ranked if self.judge_top_n is None else pool.ranked[: self.judge_top_n]
        return [(key, self.judge_texts[key]) for key in keys]

    def select(
        self, question: Mapping, pool: Pool | None = None, *, thinking: bool = True
    ) -> dict:
        """Judge one pool: the tables to report as evidence, best first.

        `picks` is what submission's `relevant_tables` should carry. `ranked` is
        picks + retrieval tail, which is what recall@K is measured on and what a
        caller should fall back to when the judge returns nothing.
        """
        if pool is None:
            pool = self.build_pool(question)
        items = self.judge_items(pool)
        picks = judge_pool_llm(question["question"], items, thinking=thinking)
        return {
            "query": pool.query,
            "n_candidates": len(pool.keys),
            "pool_size": len(pool.ranked),
            "picks": picks,
            "ranked": rerank_with_picks(pool.ranked, picks),
        }
