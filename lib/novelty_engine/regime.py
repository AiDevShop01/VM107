"""RegimeNovelty stub — Phase 83 ships the contract; Phase 66 RegimeEmitter implements scoring.

Phase 66 Lock E1: When implemented, score_regime() MUST remain deterministic.

Contract shape for Phase 66 RegimeEmitter author:
    payload keys expected:
        - regime_label (str): e.g. "TREND/HIGH_VOL", "RANGE/LOW_VOL"
        - transition_probability (float): probability of regime transition in [0.0, 1.0]
        - historical_regime_distribution (dict): mapping of regime_label -> count
        - confidence (float): model confidence in [0.0, 1.0]

    Returns: NoveltyScore (always deterministic per Phase 66 Lock E1)

    Suggested scoring rules (V2 starting point):
        +0.4 if transition_probability > 0.7 (high-probability regime shift)
        +0.3 if regime_label has not appeared in historical_regime_distribution (new regime)
        +0.2 if regime contains HIGH_VOL and prior HIGH_VOL occurrences < 3
        +0.1 if confidence > 0.8 (high-confidence signal)
        Cap at 1.0
"""
from __future__ import annotations

from typing import Callable, Optional

from .engine import NoveltyScore


def score_regime(
    payload: dict,
    history_provider: Optional[Callable] = None,
    threshold: float = 0.5,
) -> NoveltyScore:
    """STUB — Phase 83 Plan 08 ships the contract; Phase 66 RegimeEmitter will implement.

    Contract shape (for Phase 66 RegimeEmitter author):
        payload keys expected: regime_label, transition_probability,
        historical_regime_distribution, confidence.
        Returns: NoveltyScore (always deterministic per Phase 66 Lock E1).

    See module docstring for suggested V2 scoring rules.

    Raises:
        NotImplementedError: Always — this is a Phase 83 V1 stub.
    """
    raise NotImplementedError(
        "regime_novelty is a Phase 83 V1 stub. The future Phase 66 RegimeEmitter will "
        "implement scoring. Contract shape locked — see lib/novelty_engine/regime.py docstring."
    )


class RegimeNovelty:
    """Class wrapper stub for RegimeNovelty dimension (mirrors MacroNovelty OOP API)."""

    def score(
        self,
        payload: dict,
        history_provider: Optional[Callable] = None,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Delegate to score_regime (stub — raises NotImplementedError)."""
        return score_regime(payload, history_provider=history_provider, threshold=threshold)
