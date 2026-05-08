"""Phase 47.3 — V1 hardcoded threshold constants.

Every constant has a "Phase 49 will tune" annotation. Phase 49 Learning Agent
replaces these with learned values from realized outcome attribution.

Module-load assertion (OQ-1): the 9 category point allocations MUST sum to 100.
If any constant is edited so the sum is wrong, this module raises at import
time — fail fast before any evaluator runs.
"""

# === Category point allocations (LOCKED — sum must equal 100) =======
HTF_MAX_POINTS = 15
LOCATION_MAX_POINTS = 10
LIQUIDITY_MAX_POINTS = 10
STRUCTURE_MAX_POINTS = 15
MOMENTUM_MAX_POINTS = 15
COMPRESSION_MAX_POINTS = 10
PULLBACK_MAX_POINTS = 10
RR_MAX_POINTS = 10
NEWS_MAX_POINTS = 5

# Boot-time invariant — module-load assertion (OQ-1)
_TOTAL = (
    HTF_MAX_POINTS
    + LOCATION_MAX_POINTS
    + LIQUIDITY_MAX_POINTS
    + STRUCTURE_MAX_POINTS
    + MOMENTUM_MAX_POINTS
    + COMPRESSION_MAX_POINTS
    + PULLBACK_MAX_POINTS
    + RR_MAX_POINTS
    + NEWS_MAX_POINTS
)
assert _TOTAL == 100, (
    f"Phase 47.3 invariant violated: category point allocations sum to "
    f"{_TOTAL}, not 100. Adjust constants."
)

# === Per-category thresholds (Phase 49 will tune) ===================
DISPLACEMENT_BODY_ATR_STRONG = 1.5  # ATR multiples — body > this = pass
DISPLACEMENT_BODY_ATR_WEAK = 1.0
LOCATION_PREMIUM_PCT_STRONG = 0.50  # Entry within 50% of M15 swing range
LOCATION_PREMIUM_PCT_WEAK = 0.60
LIQUIDITY_PROXIMITY_ATR_STRONG = 1.0  # FVG within 1 ATR of entry
LIQUIDITY_PROXIMITY_ATR_WEAK = 1.5
RR_THRESHOLD_PASS = 1.5  # planned RR ≥ this = pass
RR_THRESHOLD_UNCLEAR = 1.0
COMPRESSION_SCORE_PASS = 0.70  # L4 range_contraction_score
COMPRESSION_SCORE_UNCLEAR = 0.40
HTF_BOS_LOOKBACK = 3  # last 3 H1 BOS events
STRUCTURE_BOS_LOOKBACK = 20  # last 20 M5 bars
PULLBACK_PROXIMITY_ATR_STRONG = 1.0
PULLBACK_PROXIMITY_ATR_WEAK = 1.5

# === Recommendation band thresholds (LOCKED — see ROADMAP) ==========
RECOMMENDATION_BAND_STRONG = 80  # >= 80 → enter
RECOMMENDATION_BAND_CONDITIONAL = 65  # 65-79 → wait
RECOMMENDATION_BAND_WEAK = 50  # 50-64 → needs_more_confirmation; <50 → avoid

# === Confidence Degradation (Phase 49 will tune) ====================
CONFIDENCE_DOCK_HIGH = -15
CONFIDENCE_DOCK_MEDIUM = -8
CONFIDENCE_DOCK_LOW = -3
BASE_CONFIDENCE = 100

# === Timeframe hierarchy ============================================
HTF_TIMEFRAME_MAP = {
    "M5": ("H1", "M15"),  # Entry M5 → HTF=H1, MTF=M15
    "M15": ("H4", "H1"),  # Entry M15 → HTF=H4, MTF=H1
    "H1": ("D", "H4"),
}
DEFAULT_ENTRY_TIMEFRAME = "M5"

# Per-category max-points exposed as a dict for Framework boot validation.
# Keys MUST match the canonical category names in framework.CATEGORY_ORDER and
# the Literal[...] enforcement in CategoryResult.name.
CATEGORY_MAX_POINTS: dict[str, int] = {
    "HTF": HTF_MAX_POINTS,
    "Location": LOCATION_MAX_POINTS,
    "Liquidity": LIQUIDITY_MAX_POINTS,
    "Structure": STRUCTURE_MAX_POINTS,
    "Momentum": MOMENTUM_MAX_POINTS,
    "Compression": COMPRESSION_MAX_POINTS,
    "Pullback": PULLBACK_MAX_POINTS,
    "RR": RR_MAX_POINTS,
    "News": NEWS_MAX_POINTS,
}
