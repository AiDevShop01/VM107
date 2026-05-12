"""Wave 0 test scaffold for Phase 60 skill registry YAMLs — CTX-§13.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-07 when skill YAML registry entries are written.

CTX-§13: All new registry/skill/ YAMLs must exist and parse correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_all_skill_yamls_parse():
    """CTX-§13 — All new registry/skill/ YAMLs exist and parse as valid YAML."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-07")
