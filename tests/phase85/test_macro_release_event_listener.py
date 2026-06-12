"""Phase 85 Plan 10 — macro_release_event_listener subscriber tests (TDD RED/GREEN).

Tests:
1. test_required_redis_url — REDIS_URL missing raises RuntimeError on _required()
2. test_valid_payload_invokes_goal_creator — valid message calls create_macro_release_goal
   with correct event_id + indicator_id
3. test_malformed_json_logged_not_raised — bad JSON → error log + loop continues
4. test_missing_indicator_id_logged_not_raised — missing required field → log + continue
5. test_missing_event_id_uses_derived_key — when event_id absent, derived from
   indicator_id + release_timestamp
6. test_sigterm_exits_loop_cleanly — SIGTERM sentinel stops the pubsub loop

Payload contract: Phase 83 publishes to ``macro.release_events`` channel.
Payload fields (from Phase 85 conftest.py canonical fixture):
  {
    "event_type": "macro_release",
    "indicator_id": "CPIAUCSL",
    "release_timestamp": "2026-06-12T12:30:00Z",
    "actual_value": 3.4,
    "consensus_value": 3.3,
    "prior_value": 3.2,
    "revision_flag": False,
    "source": "vm101.macro_calendar"
  }

Note: event_id is NOT a standalone field — it is derived as:
  f"{indicator_id}:{release_timestamp}"

The listener accepts both:
  (a) explicit "event_id" field (forward-compatible for future producers)
  (b) derived key from indicator_id + release_timestamp (Phase 83 producer)
"""
from __future__ import annotations

import json
import os
import signal
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pubsub_message(data: str) -> dict:
    """Simulate a Redis pubsub message dict for ``type='message'``."""
    return {"type": "message", "data": data, "channel": b"macro.release_events"}


def _make_subscription_message() -> dict:
    """Redis pubsub sends a 'subscribe' control message first — must be ignored."""
    return {"type": "subscribe", "data": 1, "channel": b"macro.release_events"}


# ---------------------------------------------------------------------------
# Test: _required() raises on missing env var
# ---------------------------------------------------------------------------

class TestRequiredEnvVar:
    """_required('REDIS_URL') must raise RuntimeError if env var is not set."""

    def test_required_redis_url_raises_when_unset(self, monkeypatch):
        """main() must raise RuntimeError immediately if REDIS_URL is not set."""
        monkeypatch.delenv("REDIS_URL", raising=False)

        from listeners.macro_release_event_listener import _required
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            _required("REDIS_URL")

    def test_required_returns_value_when_set(self, monkeypatch):
        """_required() returns the env var value when it is set."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from listeners.macro_release_event_listener import _required
        result = _required("REDIS_URL")
        assert result == "redis://localhost:6379/0"


# ---------------------------------------------------------------------------
# Test: valid payload triggers create_macro_release_goal
# ---------------------------------------------------------------------------

class TestValidPayloadHandling:
    """Valid release-event messages must trigger create_macro_release_goal."""

    def test_valid_payload_invokes_goal_creator_with_event_id(self, monkeypatch):
        """A well-formed message must call create_macro_release_goal(event_id=..., indicator_id=...)."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("PHASE85_RELEASE_TOPIC", "macro.release_events")

        payload = {
            "event_type": "macro_release",
            "indicator_id": "CPIAUCSL",
            "release_timestamp": "2026-06-12T12:30:00Z",
            "actual_value": 3.4,
            "consensus_value": 3.3,
            "prior_value": 3.2,
            "revision_flag": False,
            "source": "vm101.macro_calendar",
        }

        # Simulate: one message then SIGTERM-like shutdown via StopIteration
        messages = [
            _make_subscription_message(),
            _make_pubsub_message(json.dumps(payload)),
        ]

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(messages)
        mock_pubsub.subscribe = MagicMock()
        mock_pubsub.close = MagicMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = MagicMock()

        with patch("redis.from_url", return_value=mock_redis):
            with patch(
                "listeners.macro_release_event_listener.create_macro_release_goal"
            ) as mock_goal:
                from listeners.macro_release_event_listener import main
                main()

        # Expected event_id derived from indicator_id + release_timestamp
        expected_event_id = "CPIAUCSL:2026-06-12T12:30:00Z"
        mock_goal.assert_called_once_with(
            event_id=expected_event_id,
            indicator_id="CPIAUCSL",
        )

    def test_explicit_event_id_field_used_when_present(self, monkeypatch):
        """If payload contains an explicit 'event_id' field, it takes precedence."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        payload = {
            "event_id": "explicit-evt-001",
            "indicator_id": "CPIAUCSL",
            "release_timestamp": "2026-06-12T12:30:00Z",
        }

        messages = [
            _make_pubsub_message(json.dumps(payload)),
        ]

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(messages)
        mock_pubsub.close = MagicMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = MagicMock()

        with patch("redis.from_url", return_value=mock_redis):
            with patch(
                "listeners.macro_release_event_listener.create_macro_release_goal"
            ) as mock_goal:
                from listeners.macro_release_event_listener import main
                main()

        mock_goal.assert_called_once_with(
            event_id="explicit-evt-001",
            indicator_id="CPIAUCSL",
        )


# ---------------------------------------------------------------------------
# Test: malformed JSON — log + continue, do NOT crash
# ---------------------------------------------------------------------------

class TestMalformedPayloadHandling:
    """Malformed or incomplete payloads must be logged and skipped."""

    def test_malformed_json_logged_not_raised(self, monkeypatch, caplog):
        """Non-JSON data must log an error and NOT crash the listener loop."""
        import logging
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        messages = [
            _make_pubsub_message("not-valid-json{{{"),
        ]

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(messages)
        mock_pubsub.close = MagicMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = MagicMock()

        with patch("redis.from_url", return_value=mock_redis):
            with patch("listeners.macro_release_event_listener.create_macro_release_goal") as mock_goal:
                with caplog.at_level(logging.ERROR, logger="listeners.macro_release_event_listener"):
                    from listeners.macro_release_event_listener import main
                    main()  # must NOT raise

        mock_goal.assert_not_called()
        assert any("error" in r.message.lower() or "phase85_listener_error" in r.message
                   for r in caplog.records), (
            f"Expected error log for malformed JSON; got: {[r.message for r in caplog.records]}"
        )

    def test_missing_indicator_id_logged_not_raised(self, monkeypatch, caplog):
        """Payload missing 'indicator_id' must log an error and skip, not crash."""
        import logging
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Minimal payload — indicator_id is absent
        payload = {"event_type": "macro_release", "release_timestamp": "2026-06-12T12:30:00Z"}
        messages = [
            _make_pubsub_message(json.dumps(payload)),
        ]

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(messages)
        mock_pubsub.close = MagicMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = MagicMock()

        with patch("redis.from_url", return_value=mock_redis):
            with patch("listeners.macro_release_event_listener.create_macro_release_goal") as mock_goal:
                with caplog.at_level(logging.ERROR, logger="listeners.macro_release_event_listener"):
                    from listeners.macro_release_event_listener import main
                    main()  # must NOT raise

        mock_goal.assert_not_called()


# ---------------------------------------------------------------------------
# Test: subscription control messages are ignored
# ---------------------------------------------------------------------------

class TestControlMessageFiltering:
    """Redis pubsub emits 'subscribe' + 'psubscribe' control messages — ignore them."""

    def test_subscribe_control_message_ignored(self, monkeypatch):
        """Control messages (type != 'message') must be skipped without calling goal creator."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        messages = [
            _make_subscription_message(),
        ]

        mock_pubsub = MagicMock()
        mock_pubsub.listen.return_value = iter(messages)
        mock_pubsub.close = MagicMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = MagicMock()

        with patch("redis.from_url", return_value=mock_redis):
            with patch("listeners.macro_release_event_listener.create_macro_release_goal") as mock_goal:
                from listeners.macro_release_event_listener import main
                main()

        mock_goal.assert_not_called()


# ---------------------------------------------------------------------------
# Test: SIGTERM exits loop cleanly
# ---------------------------------------------------------------------------

class TestSignalHandling:
    """SIGTERM must stop the listener loop gracefully."""

    def test_sigterm_exits_loop_cleanly(self, monkeypatch, caplog):
        """SIGTERM sentinel causes the loop to stop; pubsub.close() and r.close() called."""
        import logging
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # We simulate SIGTERM by using a generator that sets shutting_down
        # indirectly — we patch signal.signal to capture the handler,
        # then inject a message that triggers shutdown.
        captured_handlers: dict[int, object] = {}

        original_signal = signal.signal

        def _capture_signal(sig, handler):
            captured_handlers[sig] = handler

        mock_pubsub = MagicMock()
        mock_pubsub.close = MagicMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_redis.close = MagicMock()

        # Generator that fires SIGTERM handler then yields no more messages
        def _messages_with_sigterm():
            # Fire SIGTERM handler synchronously before any messages
            handler = captured_handlers.get(signal.SIGTERM)
            if handler and callable(handler):
                handler(signal.SIGTERM, None)
            yield _make_subscription_message()  # Should be skipped after shutdown

        mock_pubsub.listen.return_value = _messages_with_sigterm()

        with patch("signal.signal", side_effect=_capture_signal):
            with patch("redis.from_url", return_value=mock_redis):
                with patch("listeners.macro_release_event_listener.create_macro_release_goal"):
                    from listeners.macro_release_event_listener import main
                    main()

        # pubsub.close() and r.close() must have been called for clean exit
        mock_pubsub.close.assert_called_once()
        mock_redis.close.assert_called_once()
