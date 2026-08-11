"""File-backed table repository."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from finance_qa.core.paths import TABLES_DIR
from finance_qa.modules.tools.dataframe import (
    normalize_frame,
    repair_shifted_bank_header,
    repair_shifted_multilevel_header,
)


@dataclass(frozen=True)
class CsvTableStore:
    """Load raw table CSVs and expose evaluator-facing normalized frames."""

    tables_dir: Path = TABLES_DIR

    def submission_csv_name(self, table_id: str) -> str:
        doc, pos = table_id.rsplit("|", 1)
        return f"{doc}_table_{pos}.csv"

    def source_csv(self, table_id: str) -> Path:
        doc, pos = table_id.rsplit("|", 1)
        return self.tables_dir / doc / f"table_{pos}.csv"

    def load_frame(self, table_id: str) -> pd.DataFrame:
        raw = pd.read_csv(self.source_csv(table_id), dtype=str, keep_default_na=False)
        repaired = repair_shifted_bank_header(raw)
        repaired = repair_shifted_multilevel_header(repaired)
        min_ratio = 0.25 if len(repaired) <= 5 else 0.6
        return normalize_frame(repaired, min_ratio=min_ratio)

    async def aload_frame(self, table_id: str) -> pd.DataFrame:
        """Async facade for future gather-based loaders."""
        return await asyncio.to_thread(self.load_frame, table_id)


DEFAULT_TABLE_STORE = CsvTableStore()


def submission_csv_name(table_id: str) -> str:
    return DEFAULT_TABLE_STORE.submission_csv_name(table_id)


def source_csv(table_id: str) -> Path:
    return DEFAULT_TABLE_STORE.source_csv(table_id)


def load_frame(table_id: str) -> pd.DataFrame:
    return DEFAULT_TABLE_STORE.load_frame(table_id)
