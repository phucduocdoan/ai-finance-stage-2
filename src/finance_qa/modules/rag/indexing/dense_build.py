"""Build the local bge-m3 dense index from table doc_text."""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from finance_qa.core.paths import DENSE_INDEX_PATH, DOCUMENT_TEXT_PATH
from finance_qa.modules.rag.indexing.dense import encode, load_model


@dataclass(frozen=True)
class DenseIndexBuildConfig:
    parquet_path: Path = DOCUMENT_TEXT_PATH
    out_path: Path = DENSE_INDEX_PATH
    # Which text view to encode. The pairing of column and output file is not free to choose:
    # a query vector is only meaningful against an index built from the same column, so both
    # come from the embedding client (see `retrievers.clients`), and `--backend` sets them
    # together rather than letting a caller mix them.
    column: str = "doc_text"
    limit: int | None = None


class DenseIndexBuilder:
    """Build a local bge-m3 dense index from one of the parquet's text columns."""

    def __init__(self, config: DenseIndexBuildConfig | None = None) -> None:
        self.config = config or DenseIndexBuildConfig()

    def run(self) -> int:
        cfg = self.config
        df = pd.read_parquet(cfg.parquet_path)
        if cfg.column not in df.columns:
            raise SystemExit(
                f"{cfg.parquet_path} has no {cfg.column!r} column "
                f"(has {list(df.columns)}); rebuild it with scripts/data_build/build_doc_text.py"
            )
        if cfg.limit:
            df = df.head(cfg.limit)
        texts = df[cfg.column].tolist()
        print(f"encoding {len(texts):,} {cfg.column}")

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
    from finance_qa.modules.rag.retrievers.clients import embedding_client

    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="bge-m3", help="bge-m3 | bge-m3-dense-text")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    client = embedding_client(args.backend)
    if not hasattr(client, "_model"):
        raise SystemExit(f"{args.backend} is not a local backend; see build_deepinfra_index.py")
    return DenseIndexBuilder(
        DenseIndexBuildConfig(
            out_path=client.index_path, column=client.text_column, limit=args.limit
        )
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
