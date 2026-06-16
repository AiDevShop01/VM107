"""Brain Part 2 §B9 verbatim math — hand-calc verified.

Phase 87 Wave 5 — Task 1.
"""
import pytest

from VM107.core.belief.bayesian import BeliefSnapshot, bayesian_update

pytestmark = pytest.mark.phase_87


def test_starting_at_zero_one_confirm_yields_2_3():
    prior = BeliefSnapshot(
        probability=0.5, confidence=0.5,
        evidence_count=0, contradicting_count=0,
    )
    post = bayesian_update(prior=prior, confirms_belief=True)
    # alpha = 0 + 1 + 1 = 2, beta = 0 + 1 = 1, prob = 2/3
    assert abs(post.probability - 2 / 3) < 1e-9
    assert post.evidence_count == 1
    assert post.contradicting_count == 0


def test_hand_calc_two_confirm_one_contradict():
    prior = BeliefSnapshot(
        probability=0.6, confidence=0.7,
        evidence_count=2, contradicting_count=1,
    )
    post = bayesian_update(prior=prior, confirms_belief=True)
    # alpha = 4, beta = 2, prob = 4/6 ≈ 0.6667
    assert abs(post.probability - 4 / 6) < 1e-9
    assert post.evidence_count == 3
    # variance = (4*2) / (36 * 7) ≈ 0.0317; confidence ≈ 0.9683
    assert abs(post.confidence - (1 - (4 * 2) / (36 * 7))) < 1e-9


def test_contradict_increments_contradicting():
    prior = BeliefSnapshot(
        probability=0.5, confidence=0.5,
        evidence_count=3, contradicting_count=2,
    )
    post = bayesian_update(prior=prior, confirms_belief=False)
    assert post.contradicting_count == 3
    assert post.evidence_count == 3
