"""Build resumable hosted dense indexes for embedding-client backends."""

import _bootstrap  # noqa: F401

from finance_qa.modules.rag.indexing.deepinfra_build import main


if __name__ == "__main__":
    raise SystemExit(main())
