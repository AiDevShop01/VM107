"""Phase 87 Plan 10 (Wave 5b) — LOCK-9 12h regime-transition dedup window.

Producer-side dedup: before emitting a ``regime_transition_detected``
event for a given ``(from_regime, to_regime)`` pair, ask the event store
whether the same transition fired within the last 12h. If it did, skip
the emission AND the Phase 74 notification — return the existing
``event_id`` so the caller can attach correlation metadata.

The dedup is intentionally producer-side (not consumer-side) so the
Phase 74 NotificationDispatcher only sees one notification per real
transition. Notification spam on regime-flap days is the failure mode
this lock prevents.
"""
from __future__ import annotations

from datetime import timedelta


# LOCK-9 — 12h dedup window.
DEDUP_WINDOW_HOURS: int = 12


def is_in_dedup_window(
    *,
    event_store,
    from_regime: str,
    to_regime: str,
    hours: int = DEDUP_WINDOW_HOURS,
) -> str | None:
    """Return existing event_id if same (from,to) transition fired within hours.

    Args:
        event_store: Object exposing ``query_recent(event_type,
            payload_filter, since)`` and returning ``list[dict]`` where
            each dict carries an ``event_id`` key. The dependency is
            duck-typed so unit tests can pass a ``MagicMock``.
        from_regime: The current regime (source of the transition).
        to_regime:   The candidate regime (target of the transition).
        hours:       Window length in hours. Exposed for testability;
                     production callers should NOT override.

    Returns:
        The string ``event_id`` of the most recent matching transition
        in the window, or ``None`` if no matching transition fired.
    """
    recent = event_store.query_recent(
        event_type="regime_transition_detected",
        payload_filter={"from_regime": from_regime, "to_regime": to_regime},
        since=timedelta(hours=hours),
    )
    if not recent:
        return None
    return str(recent[0]["event_id"])
