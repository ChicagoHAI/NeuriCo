"""Shared test fixtures.

Puts src/ on sys.path so tests import the core package the same way the
runtime does.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
