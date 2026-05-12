"""Wave 0 test scaffold for citation-discipline SKILL.md — CTX-§8.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-07 when the citation-discipline skill is written and
registered.

CTX-§8: citation-discipline is a constitutional skill — it must be registered,
        parseable, and valid per validate_skill().
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_skill_validates_via_validate_skill():
    """CTX-§8 — citation-discipline SKILL.md is valid per validate_skill()."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-07")
