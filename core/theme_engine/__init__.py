"""Phase 94 Wave 3a — Theme engine state machine + evidence primitives.

The Wave-0 RED scaffold (VM107/tests/test_theme_engine_state_machine.py)
imports ``core.theme_engine.state_machine``; we ship that module here and
re-export the symbols that callers (MacroThemeEngine, tests) reach for.
"""

from core.theme_engine.state_machine import (
    derive_next_state,
    HYSTERESIS_BAND_DEFAULT,
)

__all__ = ["derive_next_state", "HYSTERESIS_BAND_DEFAULT"]
