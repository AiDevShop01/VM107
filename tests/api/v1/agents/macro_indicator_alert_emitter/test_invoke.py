"""Phase 91 follow-up — POST /api/v1/agents/macro_indicator_alert_emitter/invoke.

Guards the previously-missing HTTP half of vm107.macro_indicator_alert_emitter:
the Dagster ``macro_indicator_alert_dispatch`` asset POSTed here on every FRED
release and got a 404 because the handler file never shipped. These tests pin
the handler contract (route class resolves, auth flags, pass-through to the
already-tested ``emit_for_release`` logic, 422 on a malformed body).

emit_alert_candidate is patched at its agent-module bind point so no real
envelope POST leaves the process (mirrors the logic test's seam).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_emit_alert_candidate(monkeypatch):
    """Patch emit_alert_candidate where the agent imports it — no real POST."""
    mock = MagicMock(return_value={"status": "accepted"})
    monkeypatch.setattr(
        "agents.macro_indicator_alert_emitter.agent.emit_alert_candidate",
        mock,
    )
    return mock


def _handler():
    from api.v1.agents.macro_indicator_alert_emitter.invoke import (
        MacroIndicatorAlertEmitterInvoke,
    )

    return MacroIndicatorAlertEmitterInvoke(app=None, thread_lock=None)


def test_handler_auth_flags_match_x_api_key_sibling():
    """M2M X-API-KEY endpoint — key required, no session auth, no CSRF."""
    from api.v1.agents.macro_indicator_alert_emitter.invoke import (
        MacroIndicatorAlertEmitterInvoke as H,
    )

    assert H.requires_api_key() is True
    assert H.requires_auth() is False
    assert H.requires_csrf() is False


@pytest.mark.asyncio
async def test_valid_release_emits_at_least_info_tier(mock_emit_alert_candidate):
    """A valid FRED release -> 200 with the emit_for_release contract body.

    The always-on ``release_landed`` info tier fires on every release, so a
    well-formed indicator yields emitted_count >= 1 and echoes indicator_id.
    """
    handler = _handler()
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process(
        {
            "profile_id": "vm107.macro_indicator_alert_emitter",
            "message": "emit_for_release",
            "run_mode": "sync",
            "release_event": {
                "indicator_id": "CPIAUCSL",
                "release_date": "2026-08-01",
                "value": 4.5,
                "prev_value": 3.9,
                "consensus": 4.0,
            },
        },
        request_stub,
    )

    assert response.status_code == 200, (
        f"Expected 200; got {response.status_code} "
        f"body={response.get_data(as_text=True)}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert body["indicator_id"] == "CPIAUCSL"
    assert body["skipped_no_indicator"] is False
    assert body["emitted_count"] >= 1
    assert "release_landed" in body["matched_condition_ids"]
    # The pass-through actually drove the emitter (>=1 envelope emitted).
    assert mock_emit_alert_candidate.call_count == body["emitted_count"]


@pytest.mark.asyncio
async def test_missing_release_event_returns_422(mock_emit_alert_candidate):
    """No release_event field -> 422, and the emitter is never touched."""
    handler = _handler()
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process({"message": "emit_for_release"}, request_stub)

    assert response.status_code == 422, (
        f"Expected 422; got {response.status_code}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert "release_event" in body.get("detail", "")
    mock_emit_alert_candidate.assert_not_called()


@pytest.mark.asyncio
async def test_missing_indicator_id_is_200_skipped_not_error(
    mock_emit_alert_candidate,
):
    """release_event without indicator_id -> 200 skipped_no_indicator (self-guard),
    NOT a 5xx. The emitter treats this as a benign no-op."""
    handler = _handler()
    request_stub = MagicMock()
    request_stub.args = {}

    response = await handler.process(
        {"release_event": {"release_date": "2026-08-01", "value": 4.5}},
        request_stub,
    )

    assert response.status_code == 200, (
        f"Expected 200 skipped; got {response.status_code}"
    )
    body = json.loads(response.get_data(as_text=True))
    assert body["skipped_no_indicator"] is True
    assert body["emitted_count"] == 0
    mock_emit_alert_candidate.assert_not_called()
