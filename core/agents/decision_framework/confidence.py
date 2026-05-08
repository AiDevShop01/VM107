"""Phase 47.3 — Confidence Degradation Rule.

Two sources of capability unavailability drive confidence reduction:
  1. Tools called by the runner that returned ``status='not_available'``
  2. Categories whose required capability the runner didn't even call
     (e.g., Tier-3 stubs that always return ``not_available``)

Pre-Phase 47.6: ``CATEGORY_CAPABILITY_MAP`` is hardcoded here. Phase 47.6
will read from the capability registry's ``consumed_by`` graph. This is the
single load-bearing constant — get it wrong and confidence is silently
miscomputed.

CF-1 lock: an adjustment fires ONLY when the category itself returned
``not_available`` AND the underlying capability is also unavailable. If the
category returned ``fail`` despite a capability being out (e.g., a different
signal was sufficient to fail the category), confidence is NOT docked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fingpt_core.contracts.agents.pre_trade_evaluation import ConfidenceAdjustment

from .thresholds import (
    CONFIDENCE_DOCK_HIGH,
    CONFIDENCE_DOCK_LOW,
    CONFIDENCE_DOCK_MEDIUM,
)

if TYPE_CHECKING:
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult

    from .context import EvaluationContext


# Each category → list of (capability_id, impact_tier, optional_timeframe)
# Phase 47.6 will derive this from the capability registry's consumed_by graph.
CATEGORY_CAPABILITY_MAP: dict[str, list[tuple[str, str, Optional[str]]]] = {
    "HTF": [("get_primitives", "HIGH", "H1")],
    "Location": [("get_primitives", "MEDIUM", "M15")],
    "Liquidity": [("get_liquidity_context", "HIGH", "M15")],
    "Structure": [("get_primitives", "HIGH", "M5")],
    "Momentum": [("get_primitives", "HIGH", "M5")],
    "Compression": [("get_primitives", "MEDIUM", "M5")],
    "Pullback": [
        ("get_liquidity_context", "MEDIUM", "M5"),
        ("get_primitives", "MEDIUM", "M5"),
    ],
    "RR": [],  # No capability dep — computed from journal metadata
    "News": [
        ("get_news_context", "HIGH", None),
        ("get_macro_context", "HIGH", None),
    ],
}

IMPACT_MAGNITUDE: dict[str, int] = {
    "HIGH": CONFIDENCE_DOCK_HIGH,  # -15
    "MEDIUM": CONFIDENCE_DOCK_MEDIUM,  # -8
    "LOW": CONFIDENCE_DOCK_LOW,  # -3
}


def compute_confidence_adjustments(
    ctx: "EvaluationContext",
    results: "list[CategoryResult]",
) -> list[ConfidenceAdjustment]:
    """Emit a ConfidenceAdjustment for each (category, capability) pair where
    BOTH the category returned ``not_available`` AND the capability is
    unavailable in the context (CF-1).

    Dedupe key: ``(capability_id, category_name)`` — same pair never appears
    twice in the output even if multiple lookups would otherwise produce it.
    """
    adjustments: list[ConfidenceAdjustment] = []
    seen: set[tuple[str, str]] = set()

    for cat in results:
        if cat.status != "not_available":
            continue
        for cap_id, tier, tf in CATEGORY_CAPABILITY_MAP.get(cat.name, []):
            if not ctx.is_capability_unavailable(cap_id, timeframe=tf):
                # Category is not_available for some other reason (data gap
                # other than capability outage). Don't dock confidence —
                # confidence reflects DATA AVAILABILITY only (CF-1).
                continue
            key = (cap_id, cat.name)
            if key in seen:
                continue
            seen.add(key)
            adjustments.append(
                ConfidenceAdjustment(
                    reason=f"{cap_id} unavailable (needed by {cat.name})",
                    capability_id=cap_id,
                    impact=IMPACT_MAGNITUDE[tier],
                    impact_tier=tier,
                )
            )
    return adjustments
