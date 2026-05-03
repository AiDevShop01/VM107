"""Conftest for tests/agents/ — mirrors tests/routing/conftest.py path setup."""

from __future__ import annotations

import sys
from pathlib import Path

# VM107 root is grandparent of this conftest (tests/agents/conftest.py -> tests/agents -> tests -> VM107)
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))
