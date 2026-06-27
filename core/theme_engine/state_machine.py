"""Phase 94 §H.2 — Theme lifecycle state machine.

Pure-function state derivation: ``derive_next_state(current_state,
strength, thresholds, ticks_in_current_state=0)`` returns the next
:class:`ThemeState`. No engine state, no LLM, deterministic.

The 8-state lifecycle:

    Candidate → Emerging → Strengthening → Dominant → Stable →
    Weakening → Dormant → Archived

…with non-linear re-entry: an ARCHIVED theme whose strength climbs back
above ``emerging_min_strength`` re-enters EMERGING. A DORMANT theme that
persists at very low strength for several ticks is ARCHIVED.

Hysteresis: every promotion requires ``strength >= threshold +
hysteresis_band``; every demotion requires ``strength <= threshold -
hysteresis_band``. This prevents flapping near boundary values.
"""

from __future__ import annotations

from typing import Any

from contracts.economic_intelligence.themes import ThemeState


HYSTERESIS_BAND_DEFAULT = 5

# After this many ticks at very low strength (< emerging_min - hysteresis),
# DORMANT themes are archived. Keeps the active set bounded.
DORMANT_ARCHIVE_TICKS = 5


def _validate_thresholds(thresholds: dict[str, int]) -> tuple[int, int, int, int]:
    em = int(thresholds["emerging_min_strength"])
    st = int(thresholds["strengthening_min_strength"])
    dm = int(thresholds["dominant_min_strength"])
    hyst = int(thresholds.get("hysteresis_band", HYSTERESIS_BAND_DEFAULT))
    if not (0 <= em < st < dm <= 100):
        raise ValueError(
            "thresholds must satisfy 0 <= emerging < strengthening < dominant <= 100"
        )
    if hyst < 0 or hyst > 20:
        raise ValueError("hysteresis_band must be in [0, 20]")
    return em, st, dm, hyst


def derive_next_state(
    *,
    current_state: ThemeState,
    strength: float,
    thresholds: dict[str, int],
    ticks_in_current_state: int = 0,
) -> ThemeState:
    """Pure transition function.

    Parameters
    ----------
    current_state:
        The theme's current state.
    strength:
        Latest accumulated strength score (0..100).
    thresholds:
        Dict with ``emerging_min_strength`` / ``strengthening_min_strength``
        / ``dominant_min_strength`` / optional ``hysteresis_band``.
    ticks_in_current_state:
        How many consecutive ticks the theme has been in ``current_state``.
        Only used for DORMANT → ARCHIVED transition. Default 0.

    Returns
    -------
    The next :class:`ThemeState`.
    """

    em, st, dm, hyst = _validate_thresholds(thresholds)
    s = max(0.0, min(100.0, float(strength)))

    # ── Archived: re-entry path (non-linear lifecycle, §H.2) ────────────
    if current_state is ThemeState.ARCHIVED:
        if s >= em + hyst:
            return ThemeState.EMERGING
        return ThemeState.ARCHIVED

    # ── Dormant: stays dormant unless rising, otherwise eventually archive
    if current_state is ThemeState.DORMANT:
        if s >= em + hyst:
            return ThemeState.EMERGING
        if s < max(0, em - hyst) and ticks_in_current_state >= DORMANT_ARCHIVE_TICKS:
            return ThemeState.ARCHIVED
        return ThemeState.DORMANT

    # ── Candidate: promote to EMERGING when crossing emerging + hyst ────
    if current_state is ThemeState.CANDIDATE:
        if s >= em + hyst:
            return ThemeState.EMERGING
        return ThemeState.CANDIDATE

    # ── Emerging: promote to STRENGTHENING when crossing strengthening + hyst
    if current_state is ThemeState.EMERGING:
        if s >= st + hyst:
            return ThemeState.STRENGTHENING
        if s <= max(0, em - hyst):
            return ThemeState.DORMANT
        return ThemeState.EMERGING

    # ── Strengthening: promote to DOMINANT when crossing dominant + hyst ─
    if current_state is ThemeState.STRENGTHENING:
        if s >= dm + hyst:
            return ThemeState.DOMINANT
        if s <= max(0, st - hyst):
            return ThemeState.EMERGING
        return ThemeState.STRENGTHENING

    # ── Dominant: demote to STABLE when strength drops below dominant - hyst
    if current_state is ThemeState.DOMINANT:
        if s <= dm - hyst:
            return ThemeState.STABLE
        return ThemeState.DOMINANT

    # ── Stable: demote to WEAKENING when below strengthening - hyst ─────
    if current_state is ThemeState.STABLE:
        if s <= st - hyst:
            return ThemeState.WEAKENING
        if s >= dm + hyst:
            return ThemeState.DOMINANT
        return ThemeState.STABLE

    # ── Weakening: demote to DORMANT when below emerging - hyst ─────────
    if current_state is ThemeState.WEAKENING:
        if s <= max(0, em - hyst):
            return ThemeState.DORMANT
        if s >= st + hyst:
            return ThemeState.STABLE
        return ThemeState.WEAKENING

    # Defensive default — should be unreachable since the enum is closed.
    return current_state


__all__ = ["derive_next_state", "HYSTERESIS_BAND_DEFAULT", "DORMANT_ARCHIVE_TICKS"]
