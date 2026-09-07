"""Build numeric long-format derived data from BS/IS/CF tables."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap  # noqa: F401

from finance_qa.modules.data.preprocessing.long_format import main


if __name__ == "__main__":
    raise SystemExit(main())
