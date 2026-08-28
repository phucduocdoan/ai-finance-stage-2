"""BM25 over table doc_text.

Written directly instead of pulling in `rank_bm25` because of how the pipeline
is shaped: the hard filter already cuts each question to a median of 226
candidates (docs/v0_retrieval_pipeline.md Q4), so we never score the full
corpus. All we need globally is IDF; term frequencies are computed lazily on
the shortlist. That means no 146k-document inverted index to build or hold.

IDF is still global (df over all 146,246 tables) — computing it per shortlist
would make a term's weight depend on which question asked, so "tiền" would look
discriminative inside a shortlist where every table mentions it.

Run standalone to check throughput:
  PYTHONPATH=src .venv_bge/bin/python -m finance_qa.modules.rag.indexing.bm25
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

from finance_qa.core.paths import DOCUMENT_TEXT_PATH


PARQUET_PATH = DOCUMENT_TEXT_PATH

K1 = 1.5
B = 0.75

# \w+ over unicode keeps Vietnamese diacritics as part of the token, which is
# what we want: "tiền" and "tien" are different words and the corpus is NFC.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(unicodedata.normalize("NFC", text).lower())


class BM25:
    """Global IDF + lazy per-shortlist scoring."""

    def __init__(self, doc_texts: dict[str, str]):
        self.doc_texts = doc_texts
        self._tokens: dict[str, Counter] = {}
        self._lengths: dict[str, int] = {}

        df: Counter = Counter()
        total_len = 0
        for key, text in doc_texts.items():
            toks = tokenize(text)
            total_len += len(toks)
            df.update(set(toks))

        self.n_docs = len(doc_texts)
        self.avgdl = total_len / self.n_docs if self.n_docs else 0.0
        self.idf = {
            term: math.log(1 + (self.n_docs - d + 0.5) / (d + 0.5))
            for term, d in df.items()
        }

    def _doc(self, key: str) -> tuple[Counter, int]:
        """Tokenize on first use and memoize; shortlists overlap across questions."""
        tf = self._tokens.get(key)
        if tf is None:
            toks = tokenize(self.doc_texts[key])
            tf = Counter(toks)
            self._tokens[key] = tf
            self._lengths[key] = len(toks)
        return tf, self._lengths[key]

    def score(self, query_tokens: list[str], key: str) -> float:
        tf, dl = self._doc(key)
        norm = K1 * (1 - B + B * dl / self.avgdl)
        total = 0.0
        for term in query_tokens:
            f = tf.get(term)
            if not f:
                continue
            total += self.idf.get(term, 0.0) * f * (K1 + 1) / (f + norm)
        return total

    def top_k(self, query: str, keys: list[str], k: int = 50) -> list[tuple[str, float]]:
        query_tokens = tokenize(query)
        scored = [(key, self.score(query_tokens, key)) for key in keys]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:k]


def load_doc_texts(path: Path = PARQUET_PATH) -> dict[str, str]:
    """`report_id|table_pos` -> doc_text."""
    df = pd.read_parquet(path)
    keys = df["report_id"] + "|" + df["table_pos"].astype(str)
    return dict(zip(keys, df["doc_text"]))


def main() -> int:
    t0 = time.perf_counter()
    doc_texts = load_doc_texts()
    t1 = time.perf_counter()
    bm25 = BM25(doc_texts)
    t2 = time.perf_counter()
    print(f"loaded {bm25.n_docs:,} docs in {t1 - t0:.1f}s, IDF in {t2 - t1:.1f}s")
    print(f"vocab {len(bm25.idf):,} terms, avgdl {bm25.avgdl:.1f}")

    keys = list(doc_texts)[:500]
    q = "Lãi tiền gửi ngân hàng năm 2018"
    t3 = time.perf_counter()
    for _ in range(50):
        bm25.top_k(q, keys, k=50)
    dt = (time.perf_counter() - t3) / 50
    print(f"top_k over {len(keys)} candidates: {dt * 1000:.1f} ms")
    for key, score in bm25.top_k(q, keys, k=3):
        print(f"  {score:6.2f}  {key}  {doc_texts[key][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
