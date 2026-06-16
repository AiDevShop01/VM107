"""Phase 87 Plan 10 (Wave 5b) — vm107.macro_regime_monitor background agent.

Re-exports the package's public surface so callers can simply do::

    from agents.macro_regime_monitor import MacroRegimeMonitor

Modules:
  * skill_transition_detection — REGIMES, TransitionDecision, detect_max_transition,
    _top_indicators (REQ-87-9 joint pattern)
  * dedup_window — is_in_dedup_window (LOCK-9 12h)
  * phase74_notification_client — Phase74NotificationClient + NOTIFICATION_TEMPLATE
  * agent — MacroRegimeMonitor (orchestrator)
"""
from .agent import MacroRegimeMonitor
from .dedup_window import is_in_dedup_window
from .phase74_notification_client import (
    NOTIFICATION_TEMPLATE,
    Phase74NotificationClient,
)
from .skill_transition_detection import (
    REGIMES,
    TransitionDecision,
    detect_max_transition,
)

__all__ = [
    "MacroRegimeMonitor",
    "NOTIFICATION_TEMPLATE",
    "Phase74NotificationClient",
    "REGIMES",
    "TransitionDecision",
    "detect_max_transition",
    "is_in_dedup_window",
]
