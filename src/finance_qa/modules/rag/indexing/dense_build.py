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
