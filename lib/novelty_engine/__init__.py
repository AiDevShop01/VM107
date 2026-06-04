"""NoveltyEngine V1 — shared novelty scoring infrastructure for all VM107 emitters.

Phase 66 Lock E1: NoveltyScore is ALWAYS deterministic, NEVER LLM-supplied.
Phase 66 Lock E2: NoveltyEngine colocated in VM107/lib/ as shared infra.

V1 status (Phase 83 Plan 08):
    MACRO     — LIVE implementation in macro.py (used by Plan 09 IntelligenceFeedMacroComposer)
    REGIME    — STUB in regime.py (raises NotImplementedError; Phase 66 RegimeEmitter will fill)
    STRUCTURAL— STUB in structural.py (raises NotImplementedError; Phase 66 StructuralEmitter)
    VOLATILITY— STUB in volatility.py (raises NotImplementedError; Phase 66 VolatilityEmitter)
    BEHAVIORAL— STUB in behavioral.py (raises NotImplementedError; Phase 66 BehavioralEmitter)

Public API:
    from lib.novelty_engine import NoveltyEngine, NoveltyScore, NoveltyDimensions
    from lib.novelty_engine import score_macro  # direct function access
    from lib.novelty_engine.macro import score_macro, MacroNovelty
"""
from .engine import NoveltyEngine, NoveltyScore, NoveltyDimensions
from .macro import score_macro, MacroNovelty
from .regime import score_regime, RegimeNovelty
from .structural import score_structural, StructuralNovelty
from .volatility import score_volatility, VolatilityNovelty
from .behavioral import score_behavioral, BehavioralNovelty

__all__ = [
    # Core
    "NoveltyEngine",
    "NoveltyScore",
    "NoveltyDimensions",
    # Scorer functions (canonical API)
    "score_macro",
    "score_regime",
    "score_structural",
    "score_volatility",
    "score_behavioral",
    # Class wrappers (OOP API / back-compat)
    "MacroNovelty",
    "RegimeNovelty",
    "StructuralNovelty",
    "VolatilityNovelty",
    "BehavioralNovelty",
]
