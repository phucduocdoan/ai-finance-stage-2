"""Build a bge-m3 dense index from an arbitrary doc_text parquet, to a new file.

For the dense arm of docs/retrieval_preprocessing_2026-08-21.md: the header_flat v3
hypothesis was only ever gated on BM25 (§7, `use_dense=False`), which is the channel where
an inert junk token like `2023VND` cannot move rank. bge-m3 has no inert tokens, so the
same text change has to be measured on the dense channel separately.

Refuses to write DENSE_INDEX_PATH: `tables_dense.npy` is a protected artifact
(docs/DECISIONS.md §8) and its v1 source text no longer exists, so an overwrite is
unrecoverable.

Run (needs .venv_bge -- the base conda torch cannot see the GPU):
  PYTHONPATH=src .venv_bge/bin/python scripts/build_dense_variant.py \
      --parquet data/indexes/tables_doc_text.parquet \
      --out     data/indexes/tables_dense_v2rebuilt.npy
"""

import _bootstrap  # noqa: F401

import argparse
from pathlib import Path

from finance_qa.core.paths import DENSE_INDEX_PATH
from finance_qa.modules.rag.indexing.dense_build import DenseIndexBuilder, DenseIndexBuildConfig


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--column", default="doc_text", help="text column to encode")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    if args.out.resolve() == DENSE_INDEX_PATH.resolve():
        raise SystemExit(f"refusing to overwrite the protected index {DENSE_INDEX_PATH}")
    if not args.parquet.exists():
        raise SystemExit(f"missing {args.parquet}")

    print(f"{args.parquet}[{args.column}] -> {args.out}")
    if args.column != "doc_text":
        # DenseIndexBuilder encodes the "doc_text" column by name. Rather than widen its
        # config for a probe, hand it a frame whose doc_text IS the column we want.
        import pandas as pd

        df = pd.read_parquet(args.parquet, columns=["report_id", "table_pos", args.column])
        staged = args.out.with_suffix(".staged.parquet")
        df.rename(columns={args.column: "doc_text"}).to_parquet(staged, index=False)
        args.parquet = staged

    return DenseIndexBuilder(
        DenseIndexBuildConfig(parquet_path=args.parquet, out_path=args.out, limit=args.limit)
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
