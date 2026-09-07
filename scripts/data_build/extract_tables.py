"""Extract OCR HTML tables into raw CSV files and table index metadata."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap  # noqa: F401

from finance_qa.modules.data.preprocessing.extract_tables import main


if __name__ == "__main__":
    raise SystemExit(main())
