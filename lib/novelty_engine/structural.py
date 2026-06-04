"""StructuralNovelty stub — Phase 83 ships the contract; Phase 66 StructuralEmitter implements scoring.

Phase 66 Lock E1: When implemented, score_structural() MUST remain deterministic.

Contract shape for Phase 66 StructuralEmitter author:
    payload keys expected:
        - fvg_count (int): number of Fair Value Gaps detected
        - sweep_detected (bool): True if a liquidity sweep was detected
        - breaker_block_count (int): number of breaker blocks
        - structure_shift (bool): True if market structure shifted (BOS/CHoCH)
        - timeframe (str): e.g. "H1", "H4", "D1"

    Returns: NoveltyScore (always deterministic per Phase 66 Lock E1)

    Suggested scoring rules (V2 starting point):
        +0.3 if structure_shift is True (market structure break — high structural novelty)
        +0.2 if sweep_detected is True (liquidity event)
        +0.2 if fvg_count >= 3 (multiple imbalances — unusual structure)
        +0.3 if breaker_block_count >= 2 (strong structural confluence)
        Cap at 1.0
"""
from __future__ import annotations

from typing import Callable, Optional

from .engine import NoveltyScore


def score_structural(
    payload: dict,
    history_provider: Optional[Callable] = None,
    threshold: float = 0.5,
) -> NoveltyScore:
    """STUB — Phase 83 Plan 08 ships the contract; Phase 66 StructuralEmitter will implement.

    Contract shape (for Phase 66 StructuralEmitter author):
        payload keys expected: fvg_count, sweep_detected, breaker_block_count,
        structure_shift, timeframe.
        Returns: NoveltyScore (always deterministic per Phase 66 Lock E1).

    See module docstring for suggested V2 scoring rules.

    Raises:
        NotImplementedError: Always — this is a Phase 83 V1 stub.
    """
    raise NotImplementedError(
        "structural_novelty is a Phase 83 V1 stub. The future Phase 66 StructuralEmitter will "
        "implement scoring. Contract shape locked — see lib/novelty_engine/structural.py docstring."
    )


class StructuralNovelty:
    """Class wrapper stub for StructuralNovelty dimension (mirrors MacroNovelty OOP API)."""

    def score(
        self,
        payload: dict,
        history_provider: Optional[Callable] = None,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Delegate to score_structural (stub — raises NotImplementedError)."""
        return score_structural(payload, history_provider=history_provider, threshold=threshold)
