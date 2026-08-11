"""Metadata access helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finance_qa.core.paths import QUESTION_METADATA_PATH, TABLE_METADATA_PATH


@dataclass(frozen=True)
class JsonlMetadataStore:
    """Read question/table metadata JSONL files."""

    question_path: Path = QUESTION_METADATA_PATH
    table_path: Path = TABLE_METADATA_PATH

    def questions(self) -> list[dict[str, Any]]:
        with self.question_path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def questions_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(row["id"]): row for row in self.questions()}

    def tables(self) -> list[dict[str, Any]]:
        with self.table_path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def tables_by_id(self) -> dict[str, dict[str, Any]]:
        return {f"{row['report_id']}|{row['table_pos']}": row for row in self.tables()}


DEFAULT_METADATA_STORE = JsonlMetadataStore()
