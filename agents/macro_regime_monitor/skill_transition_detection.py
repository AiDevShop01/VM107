"""Phase 87 Plan 10 (Wave 5b) — transition detection skill.

Pure-function module: given current per-regime belief snapshots + the last
12h of anchor indicator releases, compute the maximum cross-regime
transition probability. When max > LOCK-3 0.65 threshold, return a
``TransitionDecision`` naming the from→to regime and the top-3 supporting
indicators; otherwise return ``None``.

REQ-87-9 multi-indicator joint pattern: when ≥3 anchor indicators move in
the same surprise direction within the 12h window, the
``joint_pattern_detected`` flag is set on the decision and the narrative /
notification copy is required to name ≥2 of them.

LOCK-3: threshold is fixed at 0.65; calibration deferred to Plan 87-14
24h dev VM107 soak.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# LOCK-2 — the 7 regime universe. Pinned by Plan 87-05 (LOCK-10) and
# downstream macro_regime_classifier.
REGIMES: tuple[str, ...] = (
    "expansion",
    "slowdown",
    "inflation",
    "disinflation",
    "stagflation",
    "recession",
    "recovery",
)


# LOCK-3 — transition probability threshold. Any candidate regime whose
# Bayesian-posterior probability exceeds this triggers an emission.
DEFAULT_TRANSITION_THRESHOLD: float = 0.65


@dataclass(frozen=True)
class TransitionDecision:
    """Outcome of a single ``detect_max_transition`` call.

    Attributes:
        from_regime:               The current regime (per most-recent
                                   ``macro_regime_classification`` row).
        to_regime:                 The candidate regime with the highest
                                   posterior probability above threshold.
        probability:               The candidate's posterior probability
                                   (> ``DEFAULT_TRANSITION_THRESHOLD``).
        confidence:                The candidate's confidence (from
                                   BeliefStore snapshot).
        top_3_indicators:          Top 3 anchor indicators by |surprise|
                                   in the last 12h. REQ-87-9.
        joint_pattern_detected:    True when ≥3 anchor indicators in the
                                   12h window share the same surprise
                                   direction as the top indicator
                                   (REQ-87-9 joint-pattern flag).
        triggering_belief_id:      ``belief_id`` of the candidate's
                                   snapshot (provenance for the event).
    """

    from_regime: str
    to_regime: str
    probability: float
    confidence: float
    top_3_indicators: list[str] = field(default_factory=list)
    joint_pattern_detected: bool = False
    triggering_belief_id: str = ""


def detect_max_transition(
    *,
    belief_snapshots: dict[str, dict],
    current_regime: str,
    anchor_releases_last_12h: dict[str, list[dict]],
    threshold: float = DEFAULT_TRANSITION_THRESHOLD,
) -> TransitionDecision | None:
    """Return the highest-probability cross-regime transition, or None.

    Args:
        belief_snapshots: ``{regime_id: {"probability": float,
            "confidence": float, "belief_id": str, ...}}`` — typically
            the output of ``BeliefStore.query()`` for each of the 7
            regimes. Regimes missing from the dict are treated as having
            probability 0.0 (no Bayesian update yet).
        current_regime: The most-recent persisted regime (from the
            ``macro_regime_classification`` table; cold-start →
            ``"expansion"``).
        anchor_releases_last_12h: ``{indicator_id: [release_dict, ...]}``
            — the last 12h of releases per anchor indicator. Each release
            MUST carry ``release_date`` and ``surprise`` keys.
        threshold: LOCK-3 transition threshold (default 0.65). Exposed
            for testability; production callers should NOT override.

    Returns:
        ``TransitionDecision`` describing the candidate with the maximum
        ``probability > threshold``, or ``None`` if no candidate exceeds
        the threshold. The current regime is excluded from consideration
        (a regime cannot "transition to itself").
    """
    best: TransitionDecision | None = None
    for candidate, snap in belief_snapshots.items():
        if candidate == current_regime:
            continue
        try:
            probability = float(snap.get("probability", 0.0))
        except (TypeError, ValueError):
            continue
        if probability <= threshold:
            continue
        try:
            confidence = float(snap.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if best is not None and probability <= best.probability:
            continue
        top3, joint = _top_indicators(anchor_releases_last_12h)
        best = TransitionDecision(
            from_regime=current_regime,
            to_regime=candidate,
            probability=probability,
            confidence=confidence,
            top_3_indicators=top3,
            joint_pattern_detected=joint,
            triggering_belief_id=str(snap.get("belief_id", "")),
        )
    return best


def _top_indicators(
    releases_by_indicator: dict[str, list[dict]],
) -> tuple[list[str], bool]:
    """Return (top-3 indicators by |surprise|, joint-pattern flag).

    REQ-87-9 joint pattern: ``joint_pattern_detected`` is True when ≥3
    indicators are present in the 12h window AND all of the top-3
    indicators share the same surprise direction as the #1 indicator
    (i.e. signs of their latest-in-window release agree).

    Args:
        releases_by_indicator: ``{indicator_id: [release_dict, ...]}``.
            Empty lists are skipped. Releases without a ``surprise`` key
            are treated as surprise=0.

    Returns:
        ``(top_3_indicators, joint_pattern_detected)``.
    """
    # Score each indicator by |surprise| of its latest-in-window release.
    scored: list[tuple[str, float, float]] = []
    for indicator, releases in releases_by_indicator.items():
        if not releases:
            continue
        latest = max(releases, key=lambda r: r.get("release_date", ""))
        try:
            surprise = float(latest.get("surprise", 0.0))
        except (TypeError, ValueError):
            surprise = 0.0
        scored.append((indicator, abs(surprise), surprise))

    scored.sort(key=lambda x: x[1], reverse=True)
    top3 = [s[0] for s in scored[:3]]

    # Joint pattern requires ≥3 indicators AND all top-3 same direction.
    if len(scored) < 3 or len(top3) < 3:
        return top3, False

    top1_sign = _sign(scored[0][2])
    if top1_sign == 0:
        # All zero surprises — cannot establish a direction.
        return top3, False

    joint = all(_sign(s[2]) == top1_sign for s in scored[:3])
    return top3, joint


def _sign(value: float) -> int:
    """Return +1, -1, or 0 for the sign of a surprise."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
