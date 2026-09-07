"""Rebuild derived data artifacts, given the raw dataset + tables_metadata_v2.jsonl.

`data/` is not in git (see .gitignore: "unrebuildable, backed up on the
filesystem, never in git") and there is no script that derives table metadata
from raw OCR extraction (`enrich_table_metadata.py`, referenced by
metadata_enrichment.py, does not exist). This pipeline does not attempt that
gap — it treats `data/metadata/tables_metadata_v2.jsonl` as a given input and
composes the module preprocessing/indexing services that are runnable today.

Default stages (required for the live agent, agents.finance.graph, to run):
  1. enrich_questions   ViFinQA/questions/questions.jsonl + code_stock.csv
                        -> data/metadata/questions_enriched.jsonl
  2. build_doc_text     tables_metadata_v2.jsonl -> data/indexes/tables_doc_text.parquet
  3. build_dense_index  tables_doc_text.parquet -> data/indexes/tables_dense.npy
                        (local bge-m3 model; needs a GPU environment)

Optional stages, off by default:
  --extract-tables        ViFinQA/financial_statements/*_extracted.txt
                           -> data/tables/*.csv + data/metadata/tables_index.jsonl
                           Only needed if the CSVs are missing. Rewrites
                           data/tables/, so it is opt-in even on a fresh checkout.
  --with-long-format       tables_metadata_v2.jsonl -> data/derived/long_format.parquet
                           Not read by the live agent (it loads CSVs directly via
                           modules.data.table_store); only scripts/diagnostics/solve.py (an
                           abandoned rule-based prototype) and
                           scripts/dev/verify_long_format.py use this file.
  --with-deepinfra-index   tables_doc_text.parquet -> data/indexes/tables_qwen3_4b.npy
                           Alternative hosted dense backend (dense_backend="qwen3-4b"
                           in CandidateRetriever). Calls a paid API. The live
                           default backend is "bge-m3" (build_dense_index), so this
                           is not required.

Usage:
  PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/build_data_pipeline.py
  PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/build_data_pipeline.py --skip build_dense_index
  PYTHONPATH=src .venv_bge/bin/python scripts/pipeline/build_data_pipeline.py --extract-tables --with-long-format
"""
from __future__ import annotations

import argparse
import time

from finance_qa.modules.data.preprocessing.document_text import DocumentTextBuilder
from finance_qa.modules.data.preprocessing.extract_tables import TableExtractor
from finance_qa.modules.data.preprocessing.long_format import LongFormatBuilder
from finance_qa.modules.data.preprocessing.questions import QuestionEnricher
from finance_qa.modules.rag.indexing.deepinfra_build import DeepInfraIndexBuilder, DeepInfraIndexBuildConfig
from finance_qa.modules.rag.indexing.dense_build import DenseIndexBuilder


DEFAULT_STAGES = ["enrich_questions", "build_doc_text", "build_dense_index"]
ALL_STAGES = ["extract_tables", *DEFAULT_STAGES, "build_long_format", "build_deepinfra_index"]

RUN = {
    "extract_tables": lambda: TableExtractor().run(),
    "enrich_questions": lambda: QuestionEnricher().run(),
    "build_doc_text": lambda: DocumentTextBuilder().run(),
    "build_dense_index": lambda: DenseIndexBuilder().run(),
    "build_long_format": lambda: LongFormatBuilder().run(),
    "build_deepinfra_index": lambda: DeepInfraIndexBuilder(DeepInfraIndexBuildConfig(yes=True)).run(),
}


def run_stages(stages: list[str]) -> int:
    print(f"stages: {' -> '.join(stages)}\n")
    for stage in stages:
        print(f"=== {stage} ===")
        t0 = time.perf_counter()
        rc = RUN[stage]()
        elapsed = time.perf_counter() - t0
        if rc:
            print(f"--- {stage} FAILED (rc={rc}) after {elapsed:.1f}s; stopping ---")
            return rc
        print(f"--- {stage} done in {elapsed:.1f}s ---\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--extract-tables", action="store_true",
        help="also rebuild data/tables/*.csv from raw OCR (only if CSVs are missing)",
    )
    parser.add_argument(
        "--with-long-format", action="store_true",
        help="also build long_format.parquet (unused by the live agent)",
    )
    parser.add_argument(
        "--with-deepinfra-index", action="store_true",
        help="also build the hosted qwen3-4b dense index (paid API, not the live default)",
    )
    parser.add_argument(
        "--skip", action="append", default=[], choices=DEFAULT_STAGES,
        help="skip one of the default stages (repeatable)",
    )
    args = parser.parse_args(argv)

    stages = list(DEFAULT_STAGES)
    if args.extract_tables:
        stages.insert(0, "extract_tables")
    if args.with_long_format:
        stages.append("build_long_format")
    if args.with_deepinfra_index:
        stages.append("build_deepinfra_index")
    stages = [s for s in stages if s not in args.skip]

    return run_stages(stages)
