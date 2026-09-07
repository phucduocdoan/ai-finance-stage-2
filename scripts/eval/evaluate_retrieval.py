"""Evaluate retrieval stages against the curated eval set."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap  # noqa: F401

from finance_qa.evaluation.retrieval import main


if __name__ == "__main__":
    raise SystemExit(main())
