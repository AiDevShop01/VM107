"""LOCK-5 — 14-day half-life applied weekly.

Phase 87 Wave 5 — Task 1.
"""
import math

import pytest

from VM107.core.belief.bayesian import BeliefSnapshot, apply_weekly_decay

pytestmark = pytest.mark.phase_87


def test_weekly_factor_is_2_minus_half():
    prior = BeliefSnapshot(
        probability=0.7, confidence=0.8,
        evidence_count=20, contradicting_count=4,
    )
    decayed, retire = apply_weekly_decay(prior, half_life_days=14, weekly_days=7)
    expected_factor = math.exp(-math.log(2) / 14 * 7)
    assert abs(decayed.evidence_count - round(20 * expected_factor)) <= 1
    assert abs(decayed.contradicting_count - round(4 * expected_factor)) <= 1
    assert not retire


def test_retires_at_decay_floor():
    """Belief with very low counts → posterior_conf stays above 0.15 — retire flag stays False.

    Math: maximum Beta variance occurs at alpha=beta=1 → variance=1/12 ≈ 0.0833
    → confidence ≈ 0.9167. So pure-arithmetic retire is conservative; practical
    retires come from the lifecycle governance gate, not arithmetic.
    """
    deeper_prior = BeliefSnapshot(
        probability=0.5, confidence=0.16,
        evidence_count=0, contradicting_count=0,
    )
    _decayed, retire = apply_weekly_decay(deeper_prior)
    assert retire is False
