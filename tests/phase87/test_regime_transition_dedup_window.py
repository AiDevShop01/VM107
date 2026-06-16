"""Phase 87 Plan 10 — LOCK-9 12h dedup window.

Verifies that ``is_in_dedup_window`` returns the existing event_id when a
prior ``regime_transition_detected`` event with the same (from_regime,
to_regime) pair was emitted within the 12h window, and ``None`` when no
prior matching event exists.

LOCK-9 contract: producer-side dedup MUST prevent a second
``regime_transition_detected`` emission AND the cascading Phase 74
notification when the same transition would fire twice inside 12 hours.
The agent (``MacroRegimeMonitor.run_once``) consumes this helper before
calling ``event_store.emit`` or ``Phase74NotificationClient.dispatch``.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from agents.macro_regime_monitor.agent import MacroRegimeMonitor
from agents.macro_regime_monitor.dedup_window import (
    DEDUP_WINDOW_HOURS,
    is_in_dedup_window,
)


pytestmark = pytest.mark.phase_87


def test_returns_existing_event_id_within_window():
    """Recent match in window → return its event_id."""
    store = MagicMock()
    store.query_recent.return_value = [{"event_id": "e-existing"}]

    existing = is_in_dedup_window(
        event_store=store,
        from_regime="expansion",
        to_regime="stagflation",
    )

    assert existing == "e-existing"
    store.query_recent.assert_called_once()
    call = store.query_recent.call_args
    assert call.kwargs["event_type"] == "regime_transition_detected"
    assert call.kwargs["since"] == timedelta(hours=12)
    assert call.kwargs["payload_filter"] == {
        "from_regime": "expansion",
        "to_regime": "stagflation",
    }


def test_returns_none_outside_window():
    """Empty result from event store → None (no dedup)."""
    store = MagicMock()
    store.query_recent.return_value = []
    existing = is_in_dedup_window(
        event_store=store,
        from_regime="expansion",
        to_regime="stagflation",
    )
    assert existing is None


def test_dedup_window_constant_is_12_hours():
    """LOCK-9 — 12h dedup window is the contract; do not regress."""
    assert DEDUP_WINDOW_HOURS == 12


def test_run_once_skips_emission_and_notification_when_deduped(release_event_factory):
    """End-to-end — when dedup returns existing event_id, monitor MUST NOT
    emit a new event NOR dispatch a new Phase 74 notification (REQ-87-5c)."""
    beliefs = MagicMock()
    snapshots = {
        "expansion":   {"probability": 0.30, "confidence": 0.50},
        "stagflation": {"probability": 0.70, "confidence": 0.80, "belief_id": "b-s"},
        "inflation":   {"probability": 0.20, "confidence": 0.40},
        "recession":   {"probability": 0.10, "confidence": 0.40},
        "slowdown":    {"probability": 0.10, "confidence": 0.30},
        "disinflation":{"probability": 0.10, "confidence": 0.30},
        "recovery":    {"probability": 0.10, "confidence": 0.30},
    }
    beliefs.query.side_effect = lambda *, subject_type, subject_id: (
        snapshots.get(subject_id)
    )
    beliefs.propose.return_value = "b-new"

    poller = MagicMock()
    poller.poll_recent_releases.return_value = [release_event_factory()]

    events = MagicMock()
    # Dedup hit — prior matching event exists in window.
    events.query_recent.return_value = [{"event_id": "e-prior-from-3h-ago"}]

    p74_client = MagicMock()
    classifications = MagicMock()
    classifications.most_recent_regime.return_value = "expansion"

    monitor = MacroRegimeMonitor(
        belief_store=beliefs,
        anchor_release_poller=poller,
        event_store=events,
        phase74_client=p74_client,
        classification_repo=classifications,
    )
    result = monitor.run_once()

    assert result["transition_detected"] is True
    assert result["deduped"] is True
    assert result["existing_event_id"] == "e-prior-from-3h-ago"
    events.emit.assert_not_called()
    p74_client.dispatch_transition.assert_not_called()
