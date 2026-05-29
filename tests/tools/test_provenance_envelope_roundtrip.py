"""Phase 71 Wave 0 — RED tests for AIProvenanceContract round-trip through
ToolResultEnvelope (Phase 70.5 envelope substrate).

These tests INTENTIONALLY fail (xfail strict) until Plan 05 ships the
provenance-bearing envelope wiring.

Spec sources:
- CONTEXT.md Decision 6: provenance freshness_class is mapped from the
  tool's `expected_freshness_seconds` recorded in the Phase 47.6 registry
  (added by Phase 70.5 Plan 01 to CapabilitySnapshotEntry).
- RESEARCH.md Pattern 5: mapper rules
    seconds <= expected               -> live
    expected < seconds <= 3 * expected -> recent
    seconds > 3 * expected             -> stale

REQ-71-5.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _dispatch_with_provenance(tool_id: str, freshness_seconds: int):
    """Stub helper — Plan 05 will wire dispatch_tool to attach provenance.

    Currently raises NotImplementedError so tests xfail loudly.
    """
    raise NotImplementedError(
        "Plan 05 RED — AIProvenanceContract not yet round-tripped through envelope"
    )


@pytest.mark.xfail(reason="Plan 05 RED — provenance round-trip pending", strict=True)
def test_envelope_carries_ai_provenance_contract():
    """Tool envelope carries AIProvenanceContract with freshness_class set."""
    envelope = _dispatch_with_provenance(tool_id="get_trade_context", freshness_seconds=30)
    assert envelope.provenance is not None
    assert hasattr(envelope.provenance, "freshness_class")
    assert envelope.provenance.freshness_class in {"live", "recent", "stale", "invalidated"}


@pytest.mark.xfail(reason="Plan 05 RED — registry-driven freshness mapping pending", strict=True)
def test_provenance_freshness_class_matches_registry_expected_freshness():
    """freshness_class derives from tool registry's expected_freshness_seconds.

    Example: get_trade_context's registry YAML declares expected_freshness_seconds=60.
    - actual=30  -> live (30 <= 60)
    - actual=120 -> recent (60 < 120 <= 180)
    - actual=600 -> stale  (600 > 180)
    """
    live = _dispatch_with_provenance(tool_id="get_trade_context", freshness_seconds=30)
    recent = _dispatch_with_provenance(tool_id="get_trade_context", freshness_seconds=120)
    stale = _dispatch_with_provenance(tool_id="get_trade_context", freshness_seconds=600)
    assert live.provenance.freshness_class == "live"
    assert recent.provenance.freshness_class == "recent"
    assert stale.provenance.freshness_class == "stale"


@pytest.mark.xfail(reason="Plan 05 RED — confidence/uncertainty propagation pending", strict=True)
def test_envelope_confidence_and_uncertainty_match_input():
    """Caller-supplied confidence_0_100 + uncertainty propagate through envelope unchanged."""
    envelope = _dispatch_with_provenance(tool_id="get_trade_context", freshness_seconds=30)
    assert envelope.provenance.confidence_0_100 == 78
    assert envelope.provenance.uncertainty == pytest.approx(0.22)
