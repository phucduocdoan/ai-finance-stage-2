"""Build a dense index for any `clients.EmbeddingClient` backend.

Default backend is `qwen3-4b` (Qwen3-Embedding-4B on DeepInfra), the hosted
alternative to the local bge-m3 channel. Same contract either way: fp16,
L2-normalized, one row per row of data/indexes/tables_doc_text.parquet, so
`CandidateRetriever` slices whichever index with the same matmul.

  .venv_bge/bin/python scripts/build_deepinfra_index.py --yes

Each backend writes to its own `client.index_path`, and an existing file is never
overwritten -- the bge-m3 index cannot be rebuilt (metadata v1 is gone,
docs/HANDOFF.md), so clobbering it would be unrecoverable.

A hosted run costs money -- ~22M tokens for the full corpus -- so it resumes. Rows
land in a `.partial.npy` memmap as they arrive and a sidecar JSON records the
contiguous prefix that is done; an interrupted run restarts from there instead of
re-paying for what it already fetched. `--yes` is required for a full run so the
bill is never a side effect of a smoke test.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import _bootstrap  # noqa: F401

import numpy as np
import pandas as pd

from finance_qa.paths import DOCUMENT_TEXT_PATH
from finance_qa.retrieval import deepinfra
from finance_qa.retrieval.clients import EMBEDDING_BACKENDS, embedding_client


WORKERS = 4  # concurrent HTTP batches; a window of these is one resume step


def _state_for(state_path, partial_path, n: int, model: str, batch: int) -> dict | None:
    """The resumable state, or None if there is nothing compatible to resume."""
    if not (state_path.exists() and partial_path.exists()):
        return None
    state = json.loads(state_path.read_text())
    if (state["n"], state["model"], state["batch"]) != (n, model, batch):
        # Different corpus size, model or batching means the row offsets in the
        # partial file mean something else. Refusing beats silently mixing them.
        raise SystemExit(
            f"{state_path.name} was written for n={state['n']} "
            f"model={state['model']} batch={state['batch']}; "
            f"now n={n} model={model} batch={batch}. Delete it to start over."
        )
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--backend", default="qwen3-4b", choices=list(EMBEDDING_BACKENDS),
        help="embedding client to build the index for",
    )
    ap.add_argument("--limit", type=int, default=None, help="first N tables only")
    ap.add_argument("--batch", type=int, default=deepinfra.EMBED_BATCH)
    ap.add_argument("--yes", action="store_true", help="required for a full run")
    args = ap.parse_args()

    client = embedding_client(args.backend)
    # A --limit run is a smoke test, so it gets its own filename: an index with
    # the wrong row count must never sit where the retriever expects the real one.
    out_path = client.index_path
    if args.limit:
        out_path = out_path.with_suffix(f".limit{args.limit}.npy")
    partial_path = out_path.with_suffix(".partial.npy")
    state_path = out_path.with_suffix(".partial.json")
    if out_path.exists():
        raise SystemExit(f"{out_path} already exists; move it aside to rebuild")

    df = pd.read_parquet(DOCUMENT_TEXT_PATH, columns=["doc_text"])
    if args.limit:
        df = df.head(args.limit)
    texts = df["doc_text"].fillna("").tolist()
    chars = sum(len(t) for t in texts)
    print(f"{len(texts):,} doc_text, {chars / 1e6:.1f}M chars via {client.name}")

    if not args.limit and not args.yes:
        raise SystemExit("full corpus run costs money: pass --yes (or --limit N)")

    state = _state_for(state_path, partial_path, len(texts), client.name, args.batch)
    starts = list(range(0, len(texts), args.batch))
    done = state["done"] if state else 0
    if done >= len(texts):
        print("state says complete; finalizing from the partial file")
    elif done:
        print(f"resuming at row {done:,} ({done / len(texts):.0%} already paid for)")

    out = None
    if state:
        out = np.lib.format.open_memmap(partial_path, mode="r+")

    def fetch(start: int) -> tuple[int, np.ndarray]:
        return start, client.embed_documents(texts[start : start + args.batch])

    t0 = time.perf_counter()
    pending = [s for s in starts if s >= done]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for wstart in range(0, len(pending), WORKERS):
            window = pending[wstart : wstart + WORKERS]
            for start, vecs in pool.map(fetch, window):
                if out is None:
                    # The dim is the model's to declare, so the file cannot be
                    # allocated until the first response comes back.
                    out = np.lib.format.open_memmap(
                        partial_path,
                        mode="w+",
                        dtype=np.float16,
                        shape=(len(texts), vecs.shape[1]),
                    )
                out[start : start + len(vecs)] = vecs
            out.flush()
            done = window[-1] + args.batch
            state_path.write_text(json.dumps({
                "n": len(texts), "model": client.name,
                "batch": args.batch, "done": min(done, len(texts)),
            }))
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


if __name__ == "__main__":
    raise SystemExit(main())
