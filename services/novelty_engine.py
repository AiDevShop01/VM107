"""DEPRECATED — Phase 83 Plan 08 moved NoveltyEngine to VM107/lib/novelty_engine/.

This module re-exports all public symbols for back-compat. New code should import
from the new canonical path directly.

Previously this module re-exported from emitters.novelty_engine (which was the live
implementation). Both paths now point to the same canonical lib.novelty_engine location.

Migration path:
    Replace: from services.novelty_engine import NoveltyEngine, NoveltyDimensions, NoveltyScore
    With:    from lib.novelty_engine import NoveltyEngine, NoveltyDimensions, NoveltyScore
"""
import warnings

warnings.warn(
    "VM107.services.novelty_engine is deprecated as of Phase 83 Plan 08. "
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
