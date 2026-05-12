"""Wave 0 test scaffold for ConfidenceVector calculator — CTX-§9.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-04 when ConfidenceVectorCalculator is written.

CTX-§9: ConfidenceVector is computed deterministically from the sentence array
        by the orchestrator (not by the writer sub-agent).
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_deterministic_computation():
    """CTX-§9 — ConfidenceVector computed deterministically from sentence array."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-04")
