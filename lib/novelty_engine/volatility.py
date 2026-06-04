"""VolatilityNovelty stub — Phase 83 ships the contract; Phase 66 VolatilityEmitter implements scoring.

Phase 66 Lock E1: When implemented, score_volatility() MUST remain deterministic.

Contract shape for Phase 66 VolatilityEmitter author:
    payload keys expected:
        - atr_multiple (float): ATR multiple relative to baseline (1.0 = baseline)
        - volatility_regime (str): e.g. "LOW", "NORMAL", "HIGH", "EXTREME"
        - vix_equivalent (float | None): VIX or implied-vol equivalent if available
        - volatility_z_score (float | None): z-score of current vol vs 30-day baseline
        - opportunity_clustering (bool): True if multiple opportunities cluster (co-occurrence)

    Returns: NoveltyScore (always deterministic per Phase 66 Lock E1)

    Suggested scoring rules (V2 starting point):
        +0.4 if atr_multiple > 2.0 (extreme vol expansion)
        +0.2 if volatility_regime == 'EXTREME'
        +0.2 if volatility_z_score is not None and abs(volatility_z_score) > 2.0
        +0.2 if opportunity_clustering is True (co-occurrence lift per CONTEXT §4)
        Cap at 1.0

    Note: Per CONTEXT.md §2, volatility_expansion requires opportunity_clustering
    to cross threshold (co-occurrence rule). Implement this via the co-occurrence
    check on opportunity_clustering flag.
"""
from __future__ import annotations

from typing import Callable, Optional

from .engine import NoveltyScore


def score_volatility(
    payload: dict,
    history_provider: Optional[Callable] = None,
    threshold: float = 0.5,
) -> NoveltyScore:
    """STUB — Phase 83 Plan 08 ships the contract; Phase 66 VolatilityEmitter will implement.

    Contract shape (for Phase 66 VolatilityEmitter author):
        payload keys expected: atr_multiple, volatility_regime, vix_equivalent,
        volatility_z_score, opportunity_clustering.
        Returns: NoveltyScore (always deterministic per Phase 66 Lock E1).

    See module docstring for suggested V2 scoring rules.

    Raises:
        NotImplementedError: Always — this is a Phase 83 V1 stub.
    """
    raise NotImplementedError(
        "volatility_novelty is a Phase 83 V1 stub. The future Phase 66 VolatilityEmitter will "
        "implement scoring. Contract shape locked — see lib/novelty_engine/volatility.py docstring."
    )


class VolatilityNovelty:
    """Class wrapper stub for VolatilityNovelty dimension (mirrors MacroNovelty OOP API)."""

    def score(
        self,
        payload: dict,
        history_provider: Optional[Callable] = None,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Delegate to score_volatility (stub — raises NotImplementedError)."""
        return score_volatility(payload, history_provider=history_provider, threshold=threshold)
