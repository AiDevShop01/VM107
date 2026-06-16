"""Phase 87 Plan 10 — REQ-87-5b Phase 74 dispatch end-to-end.

Verifies that ``Phase74NotificationClient.dispatch_transition`` POSTs
the REQ-87-5 templated body to the Phase 74 NotificationDispatcher
``/api/v1/notifications/dispatch`` endpoint with the correct channel,
priority, and metadata shape.

Uses an ``httpx.MockTransport`` to intercept the request at the wire
level — no live Phase 74 service required.
"""
from __future__ import annotations

import json

import httpx
import pytest

from agents.macro_regime_monitor.phase74_notification_client import (
    NOTIFICATION_TEMPLATE,
    Phase74NotificationClient,
)
from agents.macro_regime_monitor.skill_transition_detection import (
    TransitionDecision,
)


pytestmark = pytest.mark.phase_87


def _capture_dispatch(monkeypatch, response_body=None):
    """Return (client, captured_dict). captured_dict is populated after
    the dispatcher is called with the JSON payload + URL + method."""
    monkeypatch.setenv("PHASE74_DISPATCHER_URL", "http://test-dispatcher")
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=response_body or {"status": "ok", "notification_id": "n-1"},
        )

    client = Phase74NotificationClient(dispatcher_url="http://test-dispatcher")
    # Swap the live httpx.Client for one wired to MockTransport.
    client._client = httpx.Client(transport=httpx.MockTransport(_handler))
    return client, captured


def test_dispatch_uses_templated_body_per_req_87_5(monkeypatch):
    """Body matches REQ-87-5 templated copy exactly."""
    client, captured = _capture_dispatch(monkeypatch)
    decision = TransitionDecision(
        from_regime="expansion",
        to_regime="stagflation",
        probability=0.72,
        confidence=0.85,
        top_3_indicators=["CPIAUCSL", "UNRATE", "GDP"],
        joint_pattern_detected=True,
        triggering_belief_id="b-1",
    )
    resp = client.dispatch_transition(decision=decision, event_id="e-1")

    assert resp["status"] == "ok"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/v1/notifications/dispatch")
    body = captured["body"]
    assert body["event_type"] == "regime_transition_detected"
    assert body["channel"] == "macro"
    assert body["priority"] == "P2"

    # REQ-87-5 templated copy — names prior, current, probability,
    # supporting indicators.
    expected_body = NOTIFICATION_TEMPLATE.format(
        prior="expansion",
        current="stagflation",
        p=0.72,
        top_3_indicators="CPIAUCSL, UNRATE, GDP",
    )
    assert body["body"] == expected_body
    # Sanity — key substrings are present.
    assert "expansion" in body["body"]
    assert "stagflation" in body["body"]
    assert "0.72" in body["body"]
    assert "CPIAUCSL" in body["body"]


def test_dispatch_metadata_contains_full_decision_context(monkeypatch):
    """Metadata block must surface every field the consumer needs."""
    client, captured = _capture_dispatch(monkeypatch)
    decision = TransitionDecision(
        from_regime="inflation",
        to_regime="stagflation",
        probability=0.81,
        confidence=0.66,
        top_3_indicators=["CPIAUCSL", "UNRATE", "NAPMPMI"],
        joint_pattern_detected=False,
        triggering_belief_id="b-xyz",
    )
    client.dispatch_transition(decision=decision, event_id="e-meta")
    metadata = captured["body"]["metadata"]
    assert metadata["event_id"] == "e-meta"
    assert metadata["from_regime"] == "inflation"
    assert metadata["to_regime"] == "stagflation"
    assert metadata["probability"] == pytest.approx(0.81)
    assert metadata["confidence"] == pytest.approx(0.66)
    assert metadata["joint_pattern_detected"] is False
    assert metadata["top_3_indicators"] == ["CPIAUCSL", "UNRATE", "NAPMPMI"]


def test_client_fail_fast_without_env(monkeypatch):
    """Missing PHASE74_DISPATCHER_URL → RuntimeError at construction time."""
    monkeypatch.delenv("PHASE74_DISPATCHER_URL", raising=False)
    with pytest.raises(RuntimeError, match="PHASE74_DISPATCHER_URL"):
        Phase74NotificationClient()


def test_client_raises_on_dispatcher_error(monkeypatch):
    """Phase 74 returning 5xx → HTTPStatusError surfaces to caller."""
    monkeypatch.setenv("PHASE74_DISPATCHER_URL", "http://test")

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "dispatcher down"})

    client = Phase74NotificationClient(dispatcher_url="http://test")
    client._client = httpx.Client(transport=httpx.MockTransport(_handler))
    decision = TransitionDecision(
        from_regime="expansion", to_regime="stagflation",
        probability=0.70, confidence=0.80,
        top_3_indicators=["CPIAUCSL"],
        joint_pattern_detected=False, triggering_belief_id="b",
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.dispatch_transition(decision=decision, event_id="e-1")
