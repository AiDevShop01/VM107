"""DEPRECATED — Phase 83 Plan 08 moved NoveltyEngine to VM107/lib/novelty_engine/.

This module re-exports all public symbols for back-compat. New code should import
from the new canonical path directly.

Migration path:
    Replace: from emitters.novelty_engine import NoveltyEngine, NoveltyDimensions, NoveltyScore
    With:    from lib.novelty_engine import NoveltyEngine, NoveltyDimensions, NoveltyScore

Note: The old emitters.novelty_engine contained a DIFFERENT NoveltyDimensions (a dataclass
with continuous float fields + boolean triggers). Plan 83-08 replaces it with a proper
Enum per Phase 66 Lock E2 decision. Any caller using the old dataclass API must migrate
to the new NoveltyEngine.score(NoveltyDimensions.MACRO, payload) dispatch API.
"""
import warnings

warnings.warn(
    "VM107.emitters.novelty_engine is deprecated as of Phase 83 Plan 08. "
    "Import from VM107.lib.novelty_engine instead.",
    DeprecationWarning,
    stacklevel=2,
)

from lib.novelty_engine import (  # noqa: F401
    NoveltyEngine,
    NoveltyScore,
    NoveltyDimensions,
    score_macro,
    score_regime,
    score_structural,
    score_volatility,
    score_behavioral,
    MacroNovelty,
    RegimeNovelty,
    StructuralNovelty,
    VolatilityNovelty,
    BehavioralNovelty,
)

__all__ = [
    "NoveltyEngine",
    "NoveltyScore",
    "NoveltyDimensions",
    "score_macro",
    "score_regime",
    "score_structural",
    "score_volatility",
    "score_behavioral",
    "MacroNovelty",
    "RegimeNovelty",
    "StructuralNovelty",
    "VolatilityNovelty",
    "BehavioralNovelty",
]
