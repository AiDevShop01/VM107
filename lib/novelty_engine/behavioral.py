"""BehavioralNovelty stub — Phase 83 ships the contract; Phase 66 BehavioralEmitter implements scoring.

Phase 66 Lock E1: When implemented, score_behavioral() MUST remain deterministic.

Contract shape for Phase 66 BehavioralEmitter author:
    payload keys expected:
        - session_edge_score (float): session-specific edge score in [0.0, 1.0]
        - behavior_anomaly (bool): True if an anomalous behavior pattern was detected
        - cross_asset_divergence (bool): True if cross-asset divergence signal is active
        - agent_confidence_delta (float): change in agent confidence vs prior session [-1.0, 1.0]
        - consecutive_loss_streak (int): number of consecutive losing trades (0 = no streak)

    Returns: NoveltyScore (always deterministic per Phase 66 Lock E1)

    Suggested scoring rules (V2 starting point):
        +0.4 if behavior_anomaly is True (anomalous pattern detected — HIGH trigger)
        +0.3 if cross_asset_divergence is True (cross-asset signal — HIGH trigger)
        +0.2 if session_edge_score > 0.8 (strong session edge = novel opportunity)
        +0.1 if consecutive_loss_streak >= 3 (behavioral risk flag)
        Cap at 1.0
"""
from __future__ import annotations

from typing import Callable, Optional

from .engine import NoveltyScore


def score_behavioral(
    payload: dict,
    history_provider: Optional[Callable] = None,
    threshold: float = 0.5,
) -> NoveltyScore:
    """STUB — Phase 83 Plan 08 ships the contract; Phase 66 BehavioralEmitter will implement.

    Contract shape (for Phase 66 BehavioralEmitter author):
        payload keys expected: session_edge_score, behavior_anomaly, cross_asset_divergence,
        agent_confidence_delta, consecutive_loss_streak.
        Returns: NoveltyScore (always deterministic per Phase 66 Lock E1).

    See module docstring for suggested V2 scoring rules.

    Raises:
        NotImplementedError: Always — this is a Phase 83 V1 stub.
    """
    raise NotImplementedError(
        "behavioral_novelty is a Phase 83 V1 stub. The future Phase 66 BehavioralEmitter will "
        "implement scoring. Contract shape locked — see lib/novelty_engine/behavioral.py docstring."
    )


class BehavioralNovelty:
    """Class wrapper stub for BehavioralNovelty dimension (mirrors MacroNovelty OOP API)."""

    def score(
        self,
        payload: dict,
        history_provider: Optional[Callable] = None,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Delegate to score_behavioral (stub — raises NotImplementedError)."""
        return score_behavioral(payload, history_provider=history_provider, threshold=threshold)
