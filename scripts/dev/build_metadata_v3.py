"""Build tables_metadata_v3.jsonl (tier-aware header_flat + unit), staged next to v2."""

import _bootstrap  # noqa: F401

from finance_qa.modules.data.preprocessing.offline.metadata_header_unit_experiment import main


if __name__ == "__main__":
    raise SystemExit(main())
