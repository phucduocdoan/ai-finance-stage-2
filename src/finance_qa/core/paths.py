"""Canonical filesystem locations used by the pipeline."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]

RAW_DATA_DIR = PROJECT_ROOT / "ViFinQA"
RAW_QUESTIONS_PATH = RAW_DATA_DIR / "questions" / "questions.jsonl"
CODE_STOCK_PATH = RAW_DATA_DIR / "code_stock.csv"
FINANCIAL_STATEMENTS_DIR = RAW_DATA_DIR / "financial_statements"

DATA_DIR = PROJECT_ROOT / "data"
TABLES_DIR = DATA_DIR / "tables"
METADATA_DIR = DATA_DIR / "metadata"
INDEXES_DIR = DATA_DIR / "indexes"
DERIVED_DIR = DATA_DIR / "derived"
EVAL_DIR = DATA_DIR / "eval"

TABLE_METADATA_PATH = METADATA_DIR / "tables_metadata_v2.jsonl"
TABLE_METADATA_V1_PATH = METADATA_DIR / "tables_metadata.jsonl"
QUESTION_METADATA_PATH = METADATA_DIR / "questions_enriched.jsonl"
DOCUMENT_TEXT_PATH = INDEXES_DIR / "tables_doc_text.parquet"
DENSE_INDEX_PATH = INDEXES_DIR / "tables_dense.npy"
# One file per dense backend, never one file rewritten in place: a second backend must not be
# able to clobber the first. `tables_dense.npy` was long believed unrebuildable (metadata v1
# is missing, see docs/HANDOFF.md); it is not -- a rebuild from the current doc_text
# reproduces it to cos 1.0000 (docs/retrieval_preprocessing_2026-08-21.md §10.1) -- but it is
# still the artifact every measured number was taken on, so it stays read-only.
QWEN3_INDEX_PATH = INDEXES_DIR / "tables_qwen3_4b.npy"
# bge-m3 over `dense_text` instead of `doc_text`. Same encoder as DENSE_INDEX_PATH, different
# text, so it must be a different file: a query vector is only meaningful against an index
# built from the same encoder *and* the same column.
DENSE_TEXT_INDEX_PATH = INDEXES_DIR / "tables_dense_dense_text.npy"
LONG_FORMAT_PATH = DERIVED_DIR / "long_format.parquet"
EVALSET_PATH = EVAL_DIR / "evalset.json"

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
RUNS_DIR = ARTIFACTS_DIR / "runs"
OUTPUT_DIR = PROJECT_ROOT / "output"
