"""Wave 0 test scaffold for Phase 60 sub-profile tool scope — CTX-§2 + CTX-§5.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-05 when tool scope enforcement for Phase 60 sub-profiles
is written.

CTX-§2: Sub-profiles have distinct tool allowlists — _writer is denied
        read-only tools like lookup_replay_artifact; _analyzer is denied
        persist-only tools like persist_narrative.
CTX-§5: Tool scope enforcement enforces the memory_scope contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_writer_denied_read_tools():
    """CTX-§2 — _writer sub-profile is denied access to lookup_replay_artifact."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-05")


def test_analyzer_denied_persist():
    """CTX-§2 — _analyzer sub-profile is denied access to persist_narrative."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-05")
