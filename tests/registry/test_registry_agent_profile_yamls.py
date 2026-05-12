"""Wave 0 test scaffold for Phase 60 agent_profile registry YAMLs — CTX-§13.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-07 when agent_profile YAML registry entries are written,
and tightened further in Plans 60-09/60-10/60-11/60-12 as profiles are added.

CTX-§13: All new registry/agent_profile/ YAMLs must exist and parse correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_all_agent_profile_yamls_parse():
    """CTX-§13 — All new registry/agent_profile/ YAMLs exist and parse as valid YAML.

    (Parameterized in 60-07; tightened in 60-09/60-10/60-11/60-12)
    """
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-07")
