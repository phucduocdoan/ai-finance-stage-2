"""Storage interfaces for finance table data."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd


class TableRepository(Protocol):
    """Read normalized financial tables by BTC table id."""

    def load_frame(self, table_id: str) -> pd.DataFrame:
        """Return the evaluator-facing DataFrame for ``table_id``."""

    def source_csv(self, table_id: str) -> Path:
        """Return the raw CSV path backing ``table_id``."""

    def submission_csv_name(self, table_id: str) -> str:
        """Return the filename expected by the submission format."""

