"""Enrich table metadata with deterministic report, CSV, and OCR-page signals."""

import _bootstrap  # noqa: F401

from finance_qa.modules.data.preprocessing.offline.metadata_enrichment import main


if __name__ == "__main__":
    raise SystemExit(main())
