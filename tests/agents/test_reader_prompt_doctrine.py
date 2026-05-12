"""Wave 0 test scaffold for reader prompt injection-resistance doctrine — CTX-§14.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-09 when reader profile prompts are written.

CTX-§14: Every _reader sub-profile prompt must contain the "treat instructions
         as data" doctrine to resist prompt-injection attacks.
         Parameterized test covers all 3 profiles (trade_auditor_agent._reader,
         behavioral_mentor_agent._reader, weekly_review_agent._reader).
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_doctrine_present_in_all_reader_prompts():
    """CTX-§14 — reader prompt contains 'treat instructions as data' doctrine
    across all 3 profiles (parameterized; tightens across waves)."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-09")
