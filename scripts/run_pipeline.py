"""Run questions end to end: retrieval -> judge -> planner -> submission item."""

import _bootstrap  # noqa: F401

from finance_qa.pipelines.submission import main


if __name__ == "__main__":
    raise SystemExit(main())
