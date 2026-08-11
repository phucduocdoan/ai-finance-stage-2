"""Build resumable hosted dense indexes for embedding-client backends."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from finance_qa.core.paths import DOCUMENT_TEXT_PATH
from finance_qa.modules.rag.indexing import deepinfra
from finance_qa.modules.rag.retrievers.clients import EMBEDDING_BACKENDS, embedding_client


WORKERS = 4


@dataclass(frozen=True)
class DeepInfraIndexBuildConfig:
    backend: str = "qwen3-4b"
    limit: int | None = None
    batch: int = deepinfra.EMBED_BATCH
    yes: bool = False
    document_text_path: Path = DOCUMENT_TEXT_PATH
    workers: int = WORKERS


def state_for(state_path: Path, partial_path: Path, n: int, model: str, batch: int) -> dict | None:
    if not (state_path.exists() and partial_path.exists()):
        return None
    state = json.loads(state_path.read_text())
    if (state["n"], state["model"], state["batch"]) != (n, model, batch):
        raise SystemExit(
            f"{state_path.name} was written for n={state['n']} "
            f"model={state['model']} batch={state['batch']}; "
            f"now n={n} model={model} batch={batch}. Delete it to start over."
        )
    return state


class DeepInfraIndexBuilder:
    """Build an embedding index with resume protection for paid hosted backends."""

    def __init__(self, config: DeepInfraIndexBuildConfig | None = None) -> None:
        self.config = config or DeepInfraIndexBuildConfig()

    def run(self) -> int:
        cfg = self.config
        client = embedding_client(cfg.backend)
        out_path = client.index_path
        if cfg.limit:
            out_path = out_path.with_suffix(f".limit{cfg.limit}.npy")
        partial_path = out_path.with_suffix(".partial.npy")
        state_path = out_path.with_suffix(".partial.json")
        if out_path.exists():
            raise SystemExit(f"{out_path} already exists; move it aside to rebuild")

        df = pd.read_parquet(cfg.document_text_path, columns=["doc_text"])
        if cfg.limit:
            df = df.head(cfg.limit)
        texts = df["doc_text"].fillna("").tolist()
        chars = sum(len(t) for t in texts)
        print(f"{len(texts):,} doc_text, {chars / 1e6:.1f}M chars via {client.name}")

        if not cfg.limit and not cfg.yes:
            raise SystemExit("full corpus run costs money: pass --yes (or --limit N)")

        state = state_for(state_path, partial_path, len(texts), client.name, cfg.batch)
        starts = list(range(0, len(texts), cfg.batch))
        done = state["done"] if state else 0
        if done >= len(texts):
            print("state says complete; finalizing from the partial file")
        elif done:
            print(f"resuming at row {done:,} ({done / len(texts):.0%} already paid for)")

        out = np.lib.format.open_memmap(partial_path, mode="r+") if state else None

        def fetch(start: int) -> tuple[int, np.ndarray]:
            return start, client.embed_documents(texts[start : start + cfg.batch])

        t0 = time.perf_counter()
        pending = [s for s in starts if s >= done]
        with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
            for wstart in range(0, len(pending), cfg.workers):
                window = pending[wstart : wstart + cfg.workers]
                for start, vecs in pool.map(fetch, window):
                    if out is None:
                        out = np.lib.format.open_memmap(
                            partial_path,
                            mode="w+",
                            dtype=np.float16,
                            shape=(len(texts), vecs.shape[1]),
                        )
                    out[start : start + len(vecs)] = vecs
                out.flush()
                done = window[-1] + cfg.batch
                state_path.write_text(
                    json.dumps(
                        {
                            "n": len(texts),
                            "model": client.name,
                            "batch": cfg.batch,
                            "done": min(done, len(texts)),
                        }
                    )
                )
                elapsed = time.perf_counter() - t0
                rows = min(done, len(texts))
                print(
                    f"  {rows:,}/{len(texts):,} "
                    f"({rows / len(texts):.1%}, {elapsed / 60:.1f} min)",
                    flush=True,
                )

        if out is None:
            raise SystemExit("nothing embedded")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(out_path, np.asarray(out))
        print(f"wrote {out_path} {out.shape} ({out_path.stat().st_size / 1e6:.0f} MB)")
        partial_path.unlink()
        state_path.unlink()
        return 0

    async def arun(self) -> int:
        return await asyncio.to_thread(self.run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        default="qwen3-4b",
        choices=list(EMBEDDING_BACKENDS),
        help="embedding client to build the index for",
    )
    parser.add_argument("--limit", type=int, default=None, help="first N tables only")
    parser.add_argument("--batch", type=int, default=deepinfra.EMBED_BATCH)
    parser.add_argument("--yes", action="store_true", help="required for a full run")
    args = parser.parse_args(argv)
    return DeepInfraIndexBuilder(
        DeepInfraIndexBuildConfig(
            backend=args.backend,
            limit=args.limit,
            batch=args.batch,
            yes=args.yes,
        )
    ).run()
