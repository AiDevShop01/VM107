"""Phase 87 Plan 10 (Wave 5b) — REQ-87-5 + VAL 87-05-04.

Verifies that ``MacroRegimeMonitor.run_once()`` emits a
``regime_transition_detected`` event when at least one candidate regime's
belief probability exceeds LOCK-3 0.65, and that no event is emitted
when all candidates remain at or below the threshold.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.macro_regime_monitor.agent import MacroRegimeMonitor


pytestmark = pytest.mark.phase_87


def _build_monitor(
    *,
    snapshot_by_subject,
    releases,
    most_recent_regime: str = "expansion",
    dedup_recent=None,
):
    """Factory: wire a MacroRegimeMonitor against MagicMock collaborators."""
    beliefs = MagicMock()
    beliefs.query.side_effect = lambda *, subject_type, subject_id: (
        snapshot_by_subject.get(subject_id)
    )
    beliefs.propose.return_value = "b-new"

    poller = MagicMock()
    poller.poll_recent_releases.return_value = releases

    events = MagicMock()
    events.query_recent.return_value = dedup_recent or []
    events.emit.return_value = "e-emitted"

    p74_client = MagicMock()
    p74_client.dispatch_transition.return_value = {"status": "ok"}

    classifications = MagicMock()
    classifications.most_recent_regime.return_value = most_recent_regime

    monitor = MacroRegimeMonitor(
        belief_store=beliefs,
        anchor_release_poller=poller,
        event_store=events,
        phase74_client=p74_client,
        classification_repo=classifications,
    )
    return monitor, beliefs, events, p74_client, classifications


def test_high_probability_emits_transition_event(release_event_factory):
    """When stagflation belief = 0.70 > 0.65, monitor emits event."""
    snapshots = {
        "expansion":   {"probability": 0.30, "confidence": 0.50, "belief_id": "b-exp"},
        "stagflation": {"probability": 0.70, "confidence": 0.80, "belief_id": "b-stag"},
        "inflation":   {"probability": 0.20, "confidence": 0.40, "belief_id": "b-inf"},
        "recession":   {"probability": 0.10, "confidence": 0.40, "belief_id": "b-rec"},
        "slowdown":    {"probability": 0.10, "confidence": 0.30, "belief_id": "b-slow"},
        "disinflation":{"probability": 0.10, "confidence": 0.30, "belief_id": "b-dis"},
        "recovery":    {"probability": 0.10, "confidence": 0.30, "belief_id": "b-recov"},
    }
    releases = [
        release_event_factory(indicator_id="CPIAUCSL", surprise=+0.2),
        release_event_factory(indicator_id="UNRATE",   surprise=+0.1),
        release_event_factory(indicator_id="GDP",      surprise=-0.3),
    ]

    monitor, _beliefs, events, p74_client, _cls = _build_monitor(
        snapshot_by_subject=snapshots, releases=releases,
    )
    result = monitor.run_once()

    assert result["transition_detected"] is True
    assert result["event_id"] == "e-emitted"
    assert result["from_regime"] == "expansion"
    assert result["to_regime"] == "stagflation"

    events.emit.assert_called_once()
    emit_kwargs = events.emit.call_args.kwargs
    assert emit_kwargs["event_type"] == "regime_transition_detected"
    payload = emit_kwargs["payload"]
    assert payload["from_regime"] == "expansion"
    assert payload["to_regime"] == "stagflation"
    assert payload["probability"] == pytest.approx(0.70)
    assert payload["triggering_belief_id"] == "b-stag"
    assert "detected_at" in payload
    p74_client.dispatch_transition.assert_called_once()


def test_below_threshold_does_not_emit(release_event_factory):
    """All belief probabilities ≤ 0.65 → no event emission, no notification."""
    snapshots = {
        regime: {"probability": 0.50, "confidence": 0.50, "belief_id": f"b-{regime}"}
        for regime in (
            "expansion", "stagflation", "inflation", "recession",
            "slowdown", "disinflation", "recovery",
        )
    }
    monitor, _beliefs, events, p74_client, _cls = _build_monitor(
        snapshot_by_subject=snapshots,
        releases=[release_event_factory()],
    )
    result = monitor.run_once()
    assert result["transition_detected"] is False
    events.emit.assert_not_called()
    p74_client.dispatch_transition.assert_not_called()


def test_cold_start_default_when_no_prior_regime(release_event_factory):
    """When classification_repo returns None, fall back to 'expansion'."""
    snapshots = {
        "expansion":   {"probability": 0.30, "confidence": 0.50, "belief_id": "b-exp"},
        "stagflation": {"probability": 0.70, "confidence": 0.80, "belief_id": "b-stag"},
    }
    monitor, _b, _e, _p, classifications = _build_monitor(
        snapshot_by_subject=snapshots,
        releases=[release_event_factory()],
        most_recent_regime=None,
    )
    result = monitor.run_once()
    assert result["transition_detected"] is True
    assert result["from_regime"] == "expansion"
    classifications.most_recent_regime.assert_called_once()


def test_monitor_uses_macro_regime_monitor_proposer_id(release_event_factory):
    """All BeliefStore.propose() calls must use proposer_id='macro_regime_monitor'
    (the second of two entries in DETERMINISTIC_PROPOSERS)."""
    snapshots = {regime: {"probability": 0.10, "confidence": 0.30}
                 for regime in (
                     "expansion", "stagflation", "inflation", "recession",
                     "slowdown", "disinflation", "recovery",
                 )}
    releases = [release_event_factory()]
    monitor, beliefs, _e, _p, _c = _build_monitor(
        snapshot_by_subject=snapshots, releases=releases,
    )
    monitor.run_once()
    for call in beliefs.propose.call_args_list:
        assert call.kwargs["proposer_id"] == "macro_regime_monitor"
