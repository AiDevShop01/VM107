"""Brain Part 2 §B9 verbatim Beta-Bernoulli Bayesian update.

Phase 87 Wave 5 — Task 1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BeliefSnapshot:
    probability: float
    confidence: float
    evidence_count: int
    contradicting_count: int


def bayesian_update(*, prior: BeliefSnapshot, confirms_belief: bool) -> BeliefSnapshot:
    """Returns posterior. alpha = evidence_count + 1, beta = contradicting_count + 1."""
    if confirms_belief:
        alpha = prior.evidence_count + 1 + 1
        beta = prior.contradicting_count + 1
    else:
        alpha = prior.evidence_count + 1
        beta = prior.contradicting_count + 1 + 1
    posterior_prob = alpha / (alpha + beta)
    # Variance of Beta(alpha, beta) = alpha*beta / ((alpha+beta)^2 * (alpha+beta+1))
    variance = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
    posterior_conf = 1.0 - variance
    return BeliefSnapshot(
        probability=posterior_prob,
        confidence=posterior_conf,
        evidence_count=alpha - 1,
        contradicting_count=beta - 1,
    )


def apply_weekly_decay(
    prior: BeliefSnapshot,
    half_life_days: int = 14,
    weekly_days: int = 7,
) -> tuple[BeliefSnapshot, bool]:
    """LOCK-5 — applies 14-day half-life decay weekly. Returns (snapshot, should_retire)."""
    factor = math.exp(-math.log(2) / half_life_days * weekly_days)
    new_evidence = int(round(prior.evidence_count * factor))
    new_contradicting = int(round(prior.contradicting_count * factor))
    alpha = new_evidence + 1
    beta = new_contradicting + 1
    post_prob = alpha / (alpha + beta)
    variance = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
    post_conf = 1.0 - variance
    snap = BeliefSnapshot(
        probability=post_prob,
        confidence=post_conf,
        evidence_count=new_evidence,
        contradicting_count=new_contradicting,
    )
    return snap, post_conf < 0.15
