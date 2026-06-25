"""Phase 91 Plan 3 Task 2 — alert_emit_hook for macro_regime_monitor.

SIDECAR module — does NOT refactor MacroRegimeMonitor's core logic. Provides
a one-line emit helper to be invoked from the existing
``MacroRegimeMonitor._emit_transition_event`` code path so each regime
transition simultaneously:

  * lands on the existing event store (unchanged)
  * fires a Phase 91 alert_candidate_created envelope through the shared
    ``core/alerts/phase91_emit.py`` shim (which POSTs to PHASE_91_UAE_URL
    or routes to DLQ when unset).

Envelope shape (alert_type='regime'):
  - subject_type    : 'regime'
  - subject_id      : transition['regime_dimension'] (inflation|growth|liquidity)
  - severity tier   : 'blocking' (B13) → 'Critical' (Phase 91 user-facing)
                       NB: 'RegimeChange' is the Phase 91 5th-tier user-facing
                       severity (LD-91-5) — the emit shim already maps via the
                       severity_translation table. We pass 'blocking' on the
                       B13 axis; the intake handler routes to the correct user
                       severity via the subscription's alert_definition.severity
                       enum (RegimeChange is a valid ORM choice).
  - extra_payload   : {new_regime, prev_regime, confidence, top_3_indicators,
                       regime_dimension, belief_store_ref}
  - event_id        : sha256(producer|subject_id|new_regime|transition_ts)[:16]

Wiring point: append a single ``emit_regime_change_alert(transition_dict)``
call inside ``MacroRegimeMonitor._emit_transition_event`` right after
``self._events.emit(...)`` returns. NO restructure of agent.py beyond that
single line.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from core.alerts.phase91_emit import emit_alert_candidate

logger = logging.getLogger(__name__)


_PRODUCER_AGENT_ID = "vm107.macro_regime_monitor"


def _event_id_for(producer: str, subject_id: str, new_regime: str, ts: str) -> str:
    raw = f"{producer}|{subject_id}|{new_regime}|{ts}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def emit_regime_change_alert(transition: dict[str, Any]) -> None:
    """Emit an alert_candidate envelope for a regime transition.

    Args:
        transition: Dict from MacroRegimeMonitor's transition event. Required keys:
            - regime_dimension : 'inflation' / 'growth' / 'liquidity'
            - new_regime       : str (one of Phase 87 LOCK-2 regimes)
            - prev_regime      : str (or None on cold-start)
            - confidence       : float
        Optional:
            - top_3_indicators       : list[str]
            - belief_store_ref       : str (Phase 71 citation)
            - transition_timestamp   : str (ISO 8601) — falls back to created_at
              auto-stamped by the shared emit shim
    """
    subject_id = transition.get("regime_dimension") or "inflation"
    new_regime = transition.get("new_regime") or "unknown"
    prev_regime = transition.get("prev_regime")
    confidence = float(transition.get("confidence") or 0.0)
    top3 = list(transition.get("top_3_indicators") or [])
    ts = transition.get("transition_timestamp") or transition.get("detected_at") or ""

    payload: dict[str, Any] = {
        "new_regime": new_regime,
        "prev_regime": prev_regime,
        "confidence": confidence,
        "top_3_indicators": top3,
        "regime_dimension": subject_id,
    }
    if transition.get("belief_store_ref"):
        payload["belief_store_ref"] = transition["belief_store_ref"]

    citations: list[str] = []
    if transition.get("belief_store_ref"):
        citations.append(transition["belief_store_ref"])

    explanation = (
        f"{subject_id.title()} regime: {prev_regime or 'unknown'} -> {new_regime} "
        f"(confidence {confidence:.2f})"
    )

    event_id = _event_id_for(_PRODUCER_AGENT_ID, subject_id, new_regime, ts)

    try:
        emit_alert_candidate(
            alert_type="regime",
            producer_agent_id=_PRODUCER_AGENT_ID,
            subject_type="regime",
            subject_id=subject_id,
            b13_internal_severity="blocking",  # → 'Critical' (Phase 91 user-facing)
            explanation=explanation,
            citations=citations,
            confidence=confidence,
            event_id=event_id,
            extra_payload=payload,
        )
    except Exception as exc:  # noqa: BLE001
        # Emit failures must NOT crash the regime monitor tick — the event
        # store already has the transition; the alert candidate is best-effort.
        logger.error({
            "event": "regime_change_alert_emit_failed",
            "subject_id": subject_id,
            "new_regime": new_regime,
            "error": str(exc),
        })


__all__ = ["emit_regime_change_alert"]
