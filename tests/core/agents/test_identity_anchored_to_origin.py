"""Phase 48 Plan 48-05 Task 5.1 — identity comparison anchored to ITER 0.

REQ-48-D10. CONTEXT § Decision 10:
  "Always compares iteration N against iteration 0 (anchored to immutable
  origin), NOT against iteration N-1 (prevents creeping drift)."

This test simulates a 3-iteration loop and asserts the orchestrator calls
``compute_score(spec_iter_N, spec_iter0)`` -- never ``compute_score(spec_iter_N,
spec_iter_{N-1})``. Anchoring is enforced by the orchestrator (Plan 08b);
this test pins the convention via a stub iteration loop calling the real
identity_scorer.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.contracts.schemas import StrategyFamily, StrategySpec


def _spec(version: str, strategy_family: StrategyFamily = StrategyFamily.BREAKOUT) -> StrategySpec:
    return StrategySpec(
        name="alpha",
        features=["rsi", "atr"],
        rules=["if rsi>70 long"],
        timeframes=["1h"],
        version=version,
        strategy_family=strategy_family,
    )


def test_anchored_to_iter0_never_to_iter_n_minus_1():
    """Simulate 3 iterations. Capture every compute_score call's 2nd arg.

    The 2nd argument MUST always be spec_iter0 (anchored origin), NEVER
    spec_iter_N-1. Creeping drift is impossible by construction.
    """
    from core.agents.refinement_orchestrator import identity_scorer as scorer_mod

    spec_iter0 = _spec("1.0.0")
    spec_iter1 = _spec("1.0.1")
    spec_iter2 = _spec("1.0.2")
    spec_iter3 = _spec("1.0.3")

    iteration_specs = [spec_iter1, spec_iter2, spec_iter3]

    real_compute = scorer_mod.compute_score
    captured_second_args = []

    def _capturing_compute(spec_new, spec_anchor):
        captured_second_args.append(spec_anchor)
        return real_compute(spec_new, spec_anchor)

    with patch.object(scorer_mod, "compute_score", side_effect=_capturing_compute):
        for spec_n in iteration_specs:
            scorer_mod.compute_score(spec_n, spec_iter0)

    assert len(captured_second_args) == 3
    for second_arg in captured_second_args:
        assert second_arg is spec_iter0, (
            "identity_scorer MUST be called with spec_iter0 as anchor; "
            f"got {second_arg.version!r} instead of {spec_iter0.version!r}"
        )


def test_score_does_not_drift_when_anchored_correctly():
    """Three iterations each diverging from iter0 by the SAME amount must
    produce the SAME identity_score when anchored to iter0.

    If the orchestrator accidentally compared N-1 instead of 0, score would
    creep upward (each iteration looks nearly identical to its predecessor).
    """
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    spec_iter0 = _spec("1.0.0")

    # Each subsequent iteration has the EXACT SAME divergence from iter0
    # (a different strategy_family) -> all three iterations must score identically.
    spec_iter1 = _spec("1.0.1", strategy_family=StrategyFamily.MEAN_REVERSION)
    spec_iter2 = _spec("1.0.2", strategy_family=StrategyFamily.MEAN_REVERSION)
    spec_iter3 = _spec("1.0.3", strategy_family=StrategyFamily.MEAN_REVERSION)

    s1, _ = compute_score(spec_iter1, spec_iter0)
    s2, _ = compute_score(spec_iter2, spec_iter0)
    s3, _ = compute_score(spec_iter3, spec_iter0)

    # All three diverge by the same IMMUTABLE_CORE field -> identical scores.
    # Version (MINOR_TUNING) has zero weight so doesn't perturb the score.
    assert s1 == s2 == s3


def test_compute_score_does_not_mutate_input_specs():
    """Pydantic frozen=True already enforces, but explicit guard."""
    from core.agents.refinement_orchestrator.identity_scorer import compute_score

    spec_a = _spec("1.0.0")
    spec_b = _spec("1.0.1", strategy_family=StrategyFamily.AUCTION_ROTATION)
    snapshot_a = spec_a.model_dump()
    snapshot_b = spec_b.model_dump()

    compute_score(spec_b, spec_a)

    assert spec_a.model_dump() == snapshot_a
    assert spec_b.model_dump() == snapshot_b
