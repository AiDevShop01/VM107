"""
VM107 emitters.scoring sub-package — Phase 66 Plan 66-06.

Re-exports canonical scoring primitives for convenience. The flat module
`emitters.scoring_primitives` is the canonical import for the RED tests;
this sub-package is the structured home for the engines used by OpportunityRanker.
"""
from emitters.scoring_primitives import (  # noqa: F401
    CategoryScoringEngine,
    StructuralGateEngine,
    UniverseResolver,
    ScoreBreakdown,
    GateResult,
    UniverseInstrument,
    CATEGORIES,
    MAX_UNIVERSE_SIZE,
    SESSION_UNIVERSES,
)
from emitters.scoring.tier_threshold_loader import TierThresholdLoader  # noqa: F401

__all__ = [
    "CategoryScoringEngine",
    "StructuralGateEngine",
    "UniverseResolver",
    "TierThresholdLoader",
    "ScoreBreakdown",
    "GateResult",
    "UniverseInstrument",
    "CATEGORIES",
    "MAX_UNIVERSE_SIZE",
    "SESSION_UNIVERSES",
]
