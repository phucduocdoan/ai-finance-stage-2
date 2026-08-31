"""Allow scripts/dev scripts to import the src-layout package without installation.

Mirrors scripts/_bootstrap.py, one directory deeper.
"""

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
