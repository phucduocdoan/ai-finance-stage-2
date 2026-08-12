"""Rebuild derived data artifacts, given the raw dataset + tables_metadata_v2.jsonl."""

import _bootstrap  # noqa: F401

from finance_qa.pipelines.data_pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
