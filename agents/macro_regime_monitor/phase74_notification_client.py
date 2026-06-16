"""Phase 87 Plan 10 (Wave 5b) — Phase 74 NotificationDispatcher client.

HTTPX client that POSTs ``regime_transition_detected`` notifications to
the Phase 74 NotificationDispatcher ``/api/v1/notifications/dispatch``
endpoint with the REQ-87-5 templated body, ``channel="macro"`` and
``priority="P2"`` (Warning).

Per CLAUDE.md ``env-driven-no-fallbacks`` lock: the dispatcher URL MUST
come from the ``PHASE74_DISPATCHER_URL`` environment variable (or be
passed explicitly to the constructor). No ``os.getenv("X", "default")``
fallbacks — fail-fast at construction time beats silently posting to the
wrong host in production.
"""
from __future__ import annotations

import os

import httpx


# REQ-87-5 acceptance copy — names prior, current, probability, top
# supporting indicators.
NOTIFICATION_TEMPLATE: str = (
    "Regime transition detected: {prior} → {current} "
    "(probability {p:.2f}). Supporting: {top_3_indicators}."
)

# Constants for the dispatcher contract (Phase 74 Plan 04 — POST body).
_CHANNEL: str = "macro"
_PRIORITY: str = "P2"   # Warning level
_EVENT_TYPE: str = "regime_transition_detected"
_DISPATCH_PATH: str = "/api/v1/notifications/dispatch"
_DEFAULT_TIMEOUT_S: float = 5.0


class Phase74NotificationClient:
    """Phase 74 NotificationDispatcher HTTPX client."""

    def __init__(
        self,
        dispatcher_url: str | None = None,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        url = dispatcher_url or os.environ.get("PHASE74_DISPATCHER_URL")
        if not url:
            raise RuntimeError(
                "PHASE74_DISPATCHER_URL required — env-driven, no default "
                "(CLAUDE.md env-driven-no-fallbacks lock)"
            )
        self._url = url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)

    def dispatch_transition(self, *, decision, event_id: str) -> dict:
        """POST a regime_transition_detected notification.

        Args:
            decision: A ``TransitionDecision`` from
                ``skill_transition_detection.detect_max_transition``.
                Must expose ``from_regime``, ``to_regime``,
                ``probability``, ``confidence``,
                ``joint_pattern_detected``, ``top_3_indicators``.
            event_id: The ``regime_transition_detected`` event_store
                id (correlation key for the consumer).

        Returns:
            The decoded JSON body of the dispatcher response.
        """
        top3_str = ", ".join(decision.top_3_indicators)
        body = NOTIFICATION_TEMPLATE.format(
            prior=decision.from_regime,
            current=decision.to_regime,
            p=float(decision.probability),
            top_3_indicators=top3_str,
        )
        payload = {
            "event_type": _EVENT_TYPE,
            "channel": _CHANNEL,
            "priority": _PRIORITY,
            "body": body,
            "metadata": {
                "event_id": event_id,
                "from_regime": decision.from_regime,
                "to_regime": decision.to_regime,
                "probability": float(decision.probability),
                "confidence": float(decision.confidence),
                "joint_pattern_detected": bool(decision.joint_pattern_detected),
                "top_3_indicators": list(decision.top_3_indicators),
            },
        }
        response = self._client.post(
            f"{self._url}{_DISPATCH_PATH}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()
