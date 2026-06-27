"""Phase 94 Wave 0 — Theme engine state machine scaffold.

GREEN as of 94-05: see ``themes/tests/test_theme_engine_state_machine.py``
and ``themes/tests/test_theme_hysteresis.py`` for the full suite. These
shims exercise the surface the Wave-0 scaffold originally pinned.
"""

from __future__ import annotations

import importlib

from contracts.economic_intelligence.themes import ThemeState


def _require_engine():
    return importlib.import_module("core.theme_engine.state_machine")


def test_strength_above_70_promotes_to_dominant():
    sm = _require_engine()
    thresholds = {
        "emerging_min_strength": 30,
        "strengthening_min_strength": 55,
        "dominant_min_strength": 70,
        "hysteresis_band": 5,
    }
    # Start in STRENGTHENING; strength must clear 70 + hysteresis to land DOMINANT.
    next_state = sm.derive_next_state(
        current_state=ThemeState.STRENGTHENING,
        strength=80,
        thresholds=thresholds,
    )
    assert next_state is ThemeState.DOMINANT


def test_hysteresis_prevents_flapping_near_threshold():
    sm = _require_engine()
    thresholds = {
        "emerging_min_strength": 30,
        "strengthening_min_strength": 55,
        "dominant_min_strength": 70,
        "hysteresis_band": 5,
    }
    state = ThemeState.STRENGTHENING
    # Oscillate around the dominant threshold within the hysteresis band; state holds.
    for s in (68, 72, 68, 72):
        state = sm.derive_next_state(
            current_state=state, strength=s, thresholds=thresholds
        )
    assert state is ThemeState.STRENGTHENING
