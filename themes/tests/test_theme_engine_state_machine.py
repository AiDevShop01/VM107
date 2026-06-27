"""Phase 94-05 — Theme engine 8-state lifecycle + hysteresis contract.

Per CONTEXT.md §H.2, themes traverse 8 non-linear lifecycle states:
Candidate → Emerging → Strengthening → Dominant → Stable → Weakening →
Dormant → Archived (with re-entry permitted from Archived/Dormant).

The state machine lives in :mod:`core.theme_engine.state_machine` and is
a PURE FUNCTION — no engine state required, no LLM, deterministic.
"""

from __future__ import annotations

import pytest

from contracts.economic_intelligence.themes import ThemeState
from core.theme_engine.state_machine import derive_next_state


def _thresholds(em=30, st=55, dm=70, hyst=5):
    return {
        "emerging_min_strength": em,
        "strengthening_min_strength": st,
        "dominant_min_strength": dm,
        "hysteresis_band": hyst,
    }


def test_strength_above_70_promotes_to_dominant():
    # Strength climbing past the dominant threshold (with hysteresis) lands
    # us in Dominant from a fresh Candidate start.
    thresholds = _thresholds()
    current = ThemeState.CANDIDATE
    # Walk up the strength scale; state should reach DOMINANT.
    final = current
    for s in (10, 35, 60, 78):
        final = derive_next_state(current_state=final, strength=s, thresholds=thresholds)
    assert final is ThemeState.DOMINANT, (
        f"strength rising past 70 must reach DOMINANT; got {final}"
    )


def test_archived_theme_can_return():
    # §H.2 lock — non-linear lifecycle. An ARCHIVED theme with rising strength
    # re-enters EMERGING (NOT directly to Dominant; re-promotion path is via
    # the standard pipeline).
    thresholds = _thresholds()
    next_state = derive_next_state(
        current_state=ThemeState.ARCHIVED,
        strength=40,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.EMERGING, (
        f"ARCHIVED theme with strength=40 must re-enter EMERGING; got {next_state}"
    )


def test_archived_with_low_strength_stays_archived():
    # Below emerging_min_strength: ARCHIVED stays put (no flapping back to Dormant).
    thresholds = _thresholds()
    next_state = derive_next_state(
        current_state=ThemeState.ARCHIVED,
        strength=10,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.ARCHIVED


def test_dominant_to_stable_when_strength_plateaus_then_weakens():
    # Plateau just below dominant promotion threshold (with hysteresis) →
    # state transitions Dominant → Stable.
    thresholds = _thresholds()
    next_state = derive_next_state(
        current_state=ThemeState.DOMINANT,
        strength=60,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.STABLE


def test_stable_to_weakening_when_strength_drops_further():
    thresholds = _thresholds()
    next_state = derive_next_state(
        current_state=ThemeState.STABLE,
        strength=40,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.WEAKENING


def test_weakening_to_dormant_when_strength_collapses():
    thresholds = _thresholds()
    next_state = derive_next_state(
        current_state=ThemeState.WEAKENING,
        strength=15,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.DORMANT


def test_dormant_to_archived_after_persistent_low_strength():
    # Two consecutive ticks at very low strength → ARCHIVED.
    thresholds = _thresholds()
    # First DORMANT tick.
    s1 = derive_next_state(
        current_state=ThemeState.DORMANT,
        strength=5,
        thresholds=thresholds,
        ticks_in_current_state=1,
    )
    # Second tick (still very low) must archive.
    s2 = derive_next_state(
        current_state=ThemeState.DORMANT,
        strength=5,
        thresholds=thresholds,
        ticks_in_current_state=10,
    )
    # First tick may stay DORMANT; second after many ticks must ARCHIVE.
    assert s2 is ThemeState.ARCHIVED


def test_candidate_to_emerging_when_strength_crosses_emerging_threshold():
    thresholds = _thresholds()
    next_state = derive_next_state(
        current_state=ThemeState.CANDIDATE,
        strength=35,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.EMERGING
