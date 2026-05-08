"""Phase 47.3 — Recommendation band derivation.

Bands:
  80+        → enter
  65-79      → wait
  50-64      → needs_more_confirmation
  <50        → avoid

Wave 0 — graduated in Plan 03 (bands module shipped).
"""
import pytest


@pytest.mark.parametrize("score, expected_band", [
    (100, "enter"),
    (90, "enter"),
    (80, "enter"),
    (79, "wait"),
    (65, "wait"),
    (64, "needs_more_confirmation"),
    (50, "needs_more_confirmation"),
    (49, "avoid"),
    (0, "avoid"),
])
def test_band_thresholds(score, expected_band):
    from core.agents.decision_framework.bands import derive_recommendation_band
    assert derive_recommendation_band(score) == expected_band
