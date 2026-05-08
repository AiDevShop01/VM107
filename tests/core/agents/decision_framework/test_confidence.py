"""Phase 47.3 — Confidence Degradation Rule tests.

Magnitudes (V1 — tunable in Phase 49):
  HIGH   → -15
  MEDIUM →  -8
  LOW    →  -3

partial_context: True only when ANY HIGH-tier capability is not_available.

Includes Critical Findings:
- CF-1: confidence only docks when CATEGORY also resolves not_available
        (data availability, not just capability availability)
- timeframe-aware capability resolution (per-timeframe failures)

Wave 0 — graduates in Plan 03 (confidence module shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — confidence module not yet shipped (Plan 03)",
    strict=False,
)


def test_high_tier_docks_15(ctx_partial_context):
    """get_macro_context not_available + Macro category not_available → -15."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_partial_context)
    high_adjustments = [a for a in result.confidence_adjustments
                        if a.impact_tier == "HIGH"]
    assert all(a.impact == -15 for a in high_adjustments)


def test_medium_tier_docks_8():
    """A MEDIUM-tier capability missing → -8."""
    raise NotImplementedError("Plan 03 ships ctx fixture for MEDIUM-only scenario")


def test_low_tier_docks_3():
    """A LOW-tier capability missing → -3."""
    raise NotImplementedError("Plan 03 ships ctx fixture for LOW-only scenario")


def test_partial_context_flag_when_any_high_unavailable(ctx_partial_context):
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_partial_context)
    assert result.partial_context is True


def test_partial_context_false_when_only_medium_low_unavailable():
    """partial_context flips ONLY on HIGH-tier loss."""
    raise NotImplementedError("Plan 03 ships fixture")


def test_dedupe_by_capability_and_category(ctx_partial_context):
    """Same (capability_id, category) pair appears only once in adjustments."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_partial_context)
    seen = set()
    for a in result.confidence_adjustments:
        key = (a.capability_id, a.reason)
        assert key not in seen
        seen.add(key)


def test_confidence_clamped_to_zero_floor():
    """OQ-9: confidence cannot go negative even if many capabilities are out."""
    from core.agents.decision_framework.framework import Framework
    # Build a synthetic ctx where 8+ HIGH-tier capabilities are not_available
    raise NotImplementedError("Plan 03 ships clamping test")


def test_confidence_only_fires_when_category_also_not_available():
    """CF-1: if get_primitives is not_available BUT HTF category resolved fail
    (because we have a different signal), don't dock confidence — confidence
    reflects DATA AVAILABILITY only."""
    raise NotImplementedError("Plan 03 ships discrimination test")


def test_is_capability_unavailable_with_timeframe_filter():
    """CF-1 extension: is_capability_unavailable('get_primitives', 'H1')
    distinguishes per-timeframe failures."""
    raise NotImplementedError("Plan 03 ships timeframe filter")
