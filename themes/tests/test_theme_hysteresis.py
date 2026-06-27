"""Phase 94-05 — Hysteresis contract.

Per CONTEXT.md §H.2: 5-point hysteresis band prevents the state machine
flapping when strength oscillates close to a threshold. The hysteresis is
applied symmetrically — you must cross threshold +/- hyst to transition.
"""

from __future__ import annotations

from contracts.economic_intelligence.themes import ThemeState
from core.theme_engine.state_machine import derive_next_state


def _thresholds(em=30, st=55, dm=70, hyst=5):
    return {
        "emerging_min_strength": em,
        "strengthening_min_strength": st,
        "dominant_min_strength": dm,
        "hysteresis_band": hyst,
    }


def test_no_flapping_near_threshold():
    """Strength oscillating around the dominant threshold MUST NOT flap state."""
    thresholds = _thresholds()
    # Start in STRENGTHENING; oscillate strength around the dominant boundary 70
    # within +/- hysteresis_band (=5). The state must NOT transition.
    state = ThemeState.STRENGTHENING
    for s in (68, 72, 68, 72, 71, 69):
        state = derive_next_state(
            current_state=state,
            strength=s,
            thresholds=thresholds,
        )
        assert state is ThemeState.STRENGTHENING, (
            f"hysteresis must hold STRENGTHENING when oscillating around 70 (got {state} at strength={s})"
        )


def test_promotion_requires_clearing_threshold_plus_hysteresis():
    """STRENGTHENING → DOMINANT only when strength reaches dominant + hysteresis."""
    thresholds = _thresholds()  # dominant=70, hyst=5
    # 74 < 70+5; should NOT promote.
    state = derive_next_state(
        current_state=ThemeState.STRENGTHENING,
        strength=74,
        thresholds=thresholds,
    )
    assert state is ThemeState.STRENGTHENING
    # 76 >= 70+5; promotes.
    state = derive_next_state(
        current_state=ThemeState.STRENGTHENING,
        strength=76,
        thresholds=thresholds,
    )
    assert state is ThemeState.DOMINANT


def test_demotion_requires_falling_below_threshold_minus_hysteresis():
    """DOMINANT → STABLE only when strength drops below dominant - hysteresis."""
    thresholds = _thresholds()  # dominant=70, hyst=5
    # 67 > 70-5; should hold DOMINANT.
    state = derive_next_state(
        current_state=ThemeState.DOMINANT,
        strength=67,
        thresholds=thresholds,
    )
    assert state is ThemeState.DOMINANT
    # 64 <= 70-5; demote to STABLE.
    state = derive_next_state(
        current_state=ThemeState.DOMINANT,
        strength=64,
        thresholds=thresholds,
    )
    assert state is ThemeState.STABLE


def test_weakening_path_deterministic():
    """Strength drop 80 → 50 traces Dominant → Stable → Weakening deterministically."""
    thresholds = _thresholds()
    state = ThemeState.DOMINANT
    state = derive_next_state(
        current_state=state, strength=80, thresholds=thresholds
    )
    assert state is ThemeState.DOMINANT  # strong enough to stay
    state = derive_next_state(
        current_state=state, strength=58, thresholds=thresholds
    )
    assert state is ThemeState.STABLE
    state = derive_next_state(
        current_state=state, strength=40, thresholds=thresholds
    )
    assert state is ThemeState.WEAKENING
