"""Pytest configuration shared across the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `pytest` to be run from the repository root without installing the
# package, so contributors can iterate quickly.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
