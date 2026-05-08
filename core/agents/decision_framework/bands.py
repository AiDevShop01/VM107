"""Phase 47.3 — Recommendation band derivation.

Maps total score to one of: enter, wait, needs_more_confirmation, avoid.
Bands locked from ROADMAP § Phase 47.3:
  >= 80  → enter
  65-79  → wait
  50-64  → needs_more_confirmation
  < 50   → avoid

Pure function. Same input → same output.
"""

from typing import Literal

from .thresholds import (
    RECOMMENDATION_BAND_CONDITIONAL,
    RECOMMENDATION_BAND_STRONG,
    RECOMMENDATION_BAND_WEAK,
)

Recommendation = Literal["enter", "wait", "avoid", "needs_more_confirmation"]


def derive_recommendation_band(score: int) -> Recommendation:
    """Pure function — score in 0..100 → recommendation band."""
    if score >= RECOMMENDATION_BAND_STRONG:
        return "enter"
    if score >= RECOMMENDATION_BAND_CONDITIONAL:
        return "wait"
    if score >= RECOMMENDATION_BAND_WEAK:
        return "needs_more_confirmation"
    return "avoid"
