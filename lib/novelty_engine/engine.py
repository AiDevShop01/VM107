"""Core NoveltyEngine, NoveltyScore dataclass, and NoveltyDimensions enum.

Phase 66 Lock E1: NoveltyScore is ALWAYS deterministic, NEVER LLM-supplied.
Phase 66 Lock E2: NoveltyEngine colocated here (VM107/lib/) as shared infra
                  for all VM107 emitters — no per-emitter NoveltyEngine drift.

All composers gate LLM enrichment on `NoveltyScore.threshold_crossed == True`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any


@dataclass(frozen=True)
class NoveltyScore:
    """Phase 66 Lock E1 canonical contract — always deterministic, never LLM-supplied.

    Produced by NoveltyEngine.score() and all dimension scorer functions.
    Composers use threshold_crossed to gate LLM enrichment calls.
    """

    score: float
    """Novelty score in [0.0, 1.0]. 0.0 = no novelty, 1.0 = maximum novelty."""

    contributing_factors: list[str]
    """Human-readable factor names explaining why the score is what it is."""

    threshold_crossed: bool
    """True when score >= threshold. Composers use this to gate LLM enrichment."""

    reason_codes: list[str]
    """Machine-parseable codes (e.g. 'FIRST_EVER_OCCURRENCE', 'Z_SCORE_GT_2', 'AUTH_FED')."""


class NoveltyDimensions(str, Enum):
    """The 5 novelty dimensions tracked by the NoveltyEngine.

    Phase 66 Lock E1: Each dimension maps to a scorer function in its own module.
    V1 (Phase 83): MACRO is live; REGIME/STRUCTURAL/VOLATILITY/BEHAVIORAL are stubs.
    V2+ (Phase 66): Stubs will be filled by future Phase 66 emitter authors.
    """

    MACRO = "macro_novelty"
    REGIME = "regime_novelty"
    STRUCTURAL = "structural_novelty"
    VOLATILITY = "volatility_novelty"
    BEHAVIORAL = "behavioral_novelty"


class NoveltyEngine:
    """Shared scorer across all VM107 emitters (Phase 66 Lock E2 — colocated infra).

    Dispatches to per-dimension scorer functions. In V1, only MACRO has a live
    implementation; the other 4 dimensions raise NotImplementedError (stubs
    for future Phase 66 emitter authors to implement against).

    Usage::

        engine = NoveltyEngine()
        result = engine.score(NoveltyDimensions.MACRO, payload, threshold=0.5)
        if result.threshold_crossed:
            # call LLM enrichment
            ...

    For tests, pass an in-memory dict-based history_provider. In production,
    pass a Redis-backed callable that returns a prior-occurrence count for an
    indicator_code.
    """

    def __init__(self, history_provider: Optional[Callable] = None) -> None:
        """Create a NoveltyEngine.

        Args:
            history_provider: Optional callable(indicator_code: str) -> int
                returning the prior occurrence count for cold-start detection.
                If None, cold-start detection is skipped (score_macro treats
                every indicator as if it has prior history).
        """
        self._history = history_provider

        # Lazy import to keep test surface clean and avoid circular imports
        from .macro import score_macro
        from .regime import score_regime
        from .structural import score_structural
        from .volatility import score_volatility
        from .behavioral import score_behavioral

        self._dispatch: dict[NoveltyDimensions, Callable] = {
            NoveltyDimensions.MACRO: score_macro,
            NoveltyDimensions.REGIME: score_regime,
            NoveltyDimensions.STRUCTURAL: score_structural,
            NoveltyDimensions.VOLATILITY: score_volatility,
            NoveltyDimensions.BEHAVIORAL: score_behavioral,
        }

    def score(
        self,
        dimension: NoveltyDimensions,
        payload: dict,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Score a payload against a single novelty dimension.

        Args:
            dimension: Which NoveltyDimension to evaluate.
            payload: Dimension-specific dict. See each scorer module's docstring
                     for the expected payload shape.
            threshold: Score threshold for threshold_crossed. Default 0.5.

        Returns:
            NoveltyScore — always deterministic.

        Raises:
            NotImplementedError: For REGIME/STRUCTURAL/VOLATILITY/BEHAVIORAL stubs.
        """
        scorer = self._dispatch[dimension]
        return scorer(payload, history_provider=self._history, threshold=threshold)

    def register_dimension(self, dimension: NoveltyDimensions, scorer: Callable) -> None:
        """Override the scorer for a dimension (for testing / future V2 plug-in).

        This allows Phase 66 emitter authors to slot in a real scorer without
        patching the module. Prefer sub-classing or dependency injection.
        """
        self._dispatch[dimension] = scorer
