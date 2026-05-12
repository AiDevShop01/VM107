"""Wave 0 test scaffold for CitationValidator — CTX-§4.

These tests are Wave 0 scaffolds: the file exists so that downstream plans'
<automated> verify blocks can reference real targets. Test bodies are
implemented in Plan 60-04 when CitationValidator is written.

CTX-§4: Every ASSERTION sentence in a narrative must have a [ref:...] citation.
        Sentences of type META must NOT have citations.
        Unknown registry_id in [ref:...] is rejected.
        SUMMARY sentences with uncited factual claims are rejected.
        Auto-bracket [UNSOURCED] fires after 2 writer retries.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_assertion_without_citation_rejected():
    """CTX-§4 — CitationValidator hard-fails ASSERTION sentence without [ref:...]."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-04")


def test_unknown_registry_id_rejected():
    """CTX-§4 — CitationValidator hard-fails citation with unknown registry_id."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-04")


def test_meta_with_citation_rejected():
    """CTX-§4 — META sentence with [ref:...] is rejected (META must not cite)."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-04")


def test_summary_uncited_assertion_rejected():
    """CTX-§4 — SUMMARY with uncited factual claim is rejected."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-04")


def test_auto_bracket_after_retries():
    """CTX-§4 — Auto-bracket [UNSOURCED] fires after 2 writer retries."""
    pytest.skip("Wave 0 scaffold — implementation lands in plan 60-04")
