"""Reclassify statement_type=="unknown" rows in tables_metadata_v2 (title rule + LLM fallback)."""

import _bootstrap  # noqa: F401

from finance_qa.modules.data.preprocessing.offline.statement_type_classifier import main


if __name__ == "__main__":
    raise SystemExit(main())
