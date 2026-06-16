"""Phase 87 Plan 10 — REQ-87-5 end-to-end.

When a high-probability transition crosses LOCK-3 0.65 and no dedup hit
is found, ``MacroRegimeMonitor.run_once()`` MUST both emit the
``regime_transition_detected`` event AND call the Phase 74
NotificationDispatcher with the templated body. This test pins the full
chain at the agent boundary.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.macro_regime_monitor.agent import MacroRegimeMonitor
from agents.macro_regime_monitor.skill_transition_detection import (
    TransitionDecision,
)


pytestmark = pytest.mark.phase_87


def _build_high_prob_monitor(release_event_factory):
    """Helper — wire a monitor with high stagflation probability."""
    beliefs = MagicMock()
    snapshots = {
        "expansion":   {"probability": 0.20, "confidence": 0.60},
        "stagflation": {"probability": 0.75, "confidence": 0.85, "belief_id": "b-s"},
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
    poller.poll_recent_releases.return_value = [
        release_event_factory(indicator_id="CPIAUCSL", surprise=+0.20),
        release_event_factory(indicator_id="UNRATE",   surprise=+0.10),
        release_event_factory(indicator_id="GDP",      surprise=-0.20),
    ]
    events = MagicMock()
    events.query_recent.return_value = []
    events.emit.return_value = "e-fired"

    p74_client = MagicMock()
    p74_client.dispatch_transition.return_value = {"status": "ok"}

    classifications = MagicMock()
    classifications.most_recent_regime.return_value = "expansion"

    monitor = MacroRegimeMonitor(
        belief_store=beliefs,
        anchor_release_poller=poller,
        event_store=events,
        phase74_client=p74_client,
        classification_repo=classifications,
    )
    return monitor, events, p74_client


def test_high_prob_triggers_emit_and_dispatch(release_event_factory):
    """run_once() emits regime_transition_detected and dispatches Phase 74."""
    monitor, events, p74_client = _build_high_prob_monitor(release_event_factory)
    result = monitor.run_once()

    assert result["transition_detected"] is True
    assert result["event_id"] == "e-fired"

    events.emit.assert_called_once()
    emit_kwargs = events.emit.call_args.kwargs
    assert emit_kwargs["event_type"] == "regime_transition_detected"
    payload = emit_kwargs["payload"]
    assert payload["from_regime"] == "expansion"
    assert payload["to_regime"] == "stagflation"
    assert payload["probability"] == pytest.approx(0.75)
    assert "detected_at" in payload

    p74_client.dispatch_transition.assert_called_once()
    decision_arg = p74_client.dispatch_transition.call_args.kwargs["decision"]
    assert isinstance(decision_arg, TransitionDecision)
    assert decision_arg.from_regime == "expansion"
    assert decision_arg.to_regime == "stagflation"
    assert decision_arg.probability == pytest.approx(0.75)
    event_id_arg = p74_client.dispatch_transition.call_args.kwargs["event_id"]
    assert event_id_arg == "e-fired"


def test_phase74_failure_does_not_crash_tick(release_event_factory):
    """If Phase 74 dispatch raises, the event is still emitted (single source
    of truth) and run_once() returns a transition-detected result."""
    monitor, events, p74_client = _build_high_prob_monitor(release_event_factory)
    p74_client.dispatch_transition.side_effect = RuntimeError(
        "dispatcher down"
    )
    result = monitor.run_once()
    assert result["transition_detected"] is True
    assert result["event_id"] == "e-fired"
    events.emit.assert_called_once()
    p74_client.dispatch_transition.assert_called_once()


def test_run_once_propagates_proposer_id_through_all_propose_calls(
    release_event_factory,
):
    """Every BeliefStore.propose() call from this agent must use the
    'macro_regime_monitor' proposer_id — the agent profile YAML's
    allowed_tools + Plan 87-09 DETERMINISTIC_PROPOSERS both require it."""
    monitor, events, _p74_client = _build_high_prob_monitor(
        release_event_factory,
    )
    monitor.run_once()
    beliefs_mock = monitor._beliefs
    assert beliefs_mock.propose.call_count > 0
    for call in beliefs_mock.propose.call_args_list:
        assert call.kwargs["proposer_id"] == "macro_regime_monitor"
