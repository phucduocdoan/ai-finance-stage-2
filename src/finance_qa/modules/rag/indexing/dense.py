"""Embed table doc_text with bge-m3 (dense channel of the V0 retriever).

bge-m3 dense is XLM-R large + CLS pooling + L2 normalize, so plain
`transformers` is enough -- no FlagEmbedding / sentence-transformers, which in
this shared env would risk downgrading torch (see "Môi trường chạy" in
docs/v0_retrieval_pipeline.md).

Must run under .venv_bge: the base conda env's torch is cu130 against a
CUDA-12.7 driver and cannot use the GPU at all.

  .venv_bge/bin/python scripts/build_dense_index.py

Output: data/indexes/tables_dense.npy, fp16 [n_tables, 1024], row order identical to
data/indexes/tables_doc_text.parquet (the key for row i is that parquet's
report_id|table_pos). No faiss index: the hard filter cuts each question to a
median of 226 candidates, so retrieval is a brute-force matmul on a slice.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoTokenizer

from finance_qa.core.paths import DENSE_INDEX_PATH, DOCUMENT_TEXT_PATH


PARQUET_PATH = DOCUMENT_TEXT_PATH
OUT_PATH = DENSE_INDEX_PATH

MODEL = "BAAI/bge-m3"
MAX_LEN = 512
BATCH = 64


def load_model():
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL, dtype=torch.float16).cuda().eval()
    return tok, model


@torch.no_grad()
def encode(texts: list[str], tok, model, batch: int = BATCH) -> np.ndarray:
    """CLS pooling + L2 normalize, fp16."""
    out = np.empty((len(texts), model.config.hidden_size), dtype=np.float16)
    # Length-sorted batches: padding to the longest member is the whole cost,
    # and doc_text length spans 2 orders of magnitude.
    order = np.argsort([len(t) for t in texts])
    for start in range(0, len(order), batch):
        idx = order[start : start + batch]
        enc = tok(
            [texts[i] for i in idx],
            padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt",
        ).to("cuda")
        vecs = model(**enc).last_hidden_state[:, 0]
        vecs = torch.nn.functional.normalize(vecs, p=2, dim=-1)
        out[idx] = vecs.cpu().numpy().astype(np.float16)
    return out


def encode_queries(texts: list[str], tok, model) -> np.ndarray:
    """bge-m3 is symmetric -- no query prefix, same encoder as documents."""
    return encode(texts, tok, model)


class BgeM3Embedder:
    """`clients.EmbeddingClient` for the local index. Loads the GPU model on first use."""

    name = "bge-m3"
    index_path = DENSE_INDEX_PATH

    def __init__(self) -> None:
        self._loaded = None

    def _model(self):
        if self._loaded is None:
            self._loaded = load_model()
        return self._loaded

    def embed_documents(self, texts):
        return encode(list(texts), *self._model())

    def embed_queries(self, texts):
        return encode_queries(list(texts), *self._model())


@dataclass(frozen=True)
class DenseIndexBuildConfig:
    parquet_path: Path = PARQUET_PATH
    out_path: Path = OUT_PATH
    limit: int | None = None


class DenseIndexBuilder:
    """Build the local bge-m3 dense index from table doc_text."""

    def __init__(self, config: DenseIndexBuildConfig | None = None) -> None:
        self.config = config or DenseIndexBuildConfig()

    def run(self) -> int:
        cfg = self.config
        df = pd.read_parquet(cfg.parquet_path)
        if cfg.limit:
            df = df.head(cfg.limit)
        texts = df["doc_text"].tolist()
        print(f"encoding {len(texts):,} doc_text")

        tok, model = load_model()
        t0 = time.perf_counter()
        vecs = encode(texts, tok, model)
        dt = time.perf_counter() - t0

        cfg.out_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(cfg.out_path, vecs)
        print(f"{vecs.shape} fp16 in {dt / 60:.1f} min ({len(texts) / dt:.0f} doc/s)")
        print(f"peak VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} GB")
        print(f"wrote {cfg.out_path} ({cfg.out_path.stat().st_size / 1e6:.0f} MB)")
        return 0

    async def arun(self) -> int:
        return await asyncio.to_thread(self.run)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    return DenseIndexBuilder(DenseIndexBuildConfig(limit=args.limit)).run()


if __name__ == "__main__":
    raise SystemExit(main())
