"""Phase 91 Plan 2 — vm107.macro_indicator_alert_emitter package.

Re-exports the package's public surface so callers can simply do::

    from agents.macro_indicator_alert_emitter import (
        MacroIndicatorAlertEmitter,
        emit_for_release,
        INDICATOR_DEFAULT_CONDITIONS,
    )

Modules:
  * conditions — INDICATOR_DEFAULT_CONDITIONS catalog + always-on info tier
  * agent      — MacroIndicatorAlertEmitter (orchestrator) + emit_for_release shim
"""
from .agent import MacroIndicatorAlertEmitter, emit_for_release
from .conditions import (
    INDICATOR_DEFAULT_CONDITIONS,
    RELEASE_LANDED_INFO_CONDITION,
)

__all__ = [
    "MacroIndicatorAlertEmitter",
    "emit_for_release",
    "INDICATOR_DEFAULT_CONDITIONS",
    "RELEASE_LANDED_INFO_CONDITION",
]
