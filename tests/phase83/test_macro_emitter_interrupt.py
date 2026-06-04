"""REQ-83-G1 (Pitfall 8) — IntelligenceFeedMacroEmitter Redis interrupt fires within 1s.

Phase 83 Plan 10 — GREENs these tests by shipping:
  VM107/emitters/intelligence_feed_macro_emitter.py (_sleep_with_interrupts method)

Pitfall 8 (from CONTEXT.md): If the emitter uses time.sleep(60) in a tight loop,
a Redis interrupt signal cannot break the loop within 1 second. The emitter must
use polling sleep (small sleep + check interrupt) pattern so it wakes on pubsub messages.
"""
import os
import sys
import time
import threading
import pytest
from unittest.mock import MagicMock


def _clear_emitter_module():
    for mod in list(sys.modules.keys()):
        if "intelligence_feed_macro_emitter" in mod and "composer" not in mod:
            del sys.modules[mod]


def _setup_env():
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-jwt"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_ENABLED"] = "true"
    os.environ["MACRO_EMITTER_INTERRUPT_POLL_SEC"] = "0.05"  # Fast polling for tests


@pytest.mark.phase83
def test_redis_interrupt_fires_within_1s():
    """Sending a Redis message to the interrupt channel stops _sleep_with_interrupts within 1s.

    REQ-83-G1, Pitfall 8: The emitter loop must not sleep for the full cadence
    interval without checking for interrupt signals.

    Plan 10 Task 2 — uses _sleep_with_interrupts directly with a mock pubsub
    that delivers a message after 0.1s, asserts it returns in under 1s.
    """
    _setup_env()
    _clear_emitter_module()

    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter

    mock_composer = MagicMock()
    mock_state = MagicMock()
    mock_state.detect_state.return_value = "OPEN"
    mock_writer = MagicMock()
    mock_writer.write.return_value = 1
    mock_cache = MagicMock()
    mock_cache.read.return_value = None
    mock_redis = MagicMock()

    emitter = IntelligenceFeedMacroEmitter(
        composer=mock_composer,
        state_client=mock_state,
        snapshot_writer=mock_writer,
        snapshot_cache=mock_cache,
        redis_client=mock_redis,
    )

    # Mock pubsub: first few calls return None, then deliver an interrupt message
    interrupt_msg = {"type": "message", "channel": b"macro.calendar.event_published", "data": b"{}"}
    call_count = 0
    null_returns = 3  # ~0.15s delay with 0.05s poll

    def get_message_side_effect(timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count > null_returns:
            return interrupt_msg
        return None

    mock_pubsub = MagicMock()
    mock_pubsub.get_message.side_effect = get_message_side_effect

    start = time.monotonic()
    # cadence=30s — normally would sleep 30 full seconds; interrupt must cut it short
    result = emitter._sleep_with_interrupts(30, mock_pubsub)
    elapsed = time.monotonic() - start

    assert result == interrupt_msg, "Expected the interrupt message to be returned"
    assert elapsed < 1.0, f"Expected interrupt within 1s, took {elapsed:.3f}s (Pitfall 8)"


@pytest.mark.phase83
def test_emitter_graceful_shutdown_on_sigterm():
    """IntelligenceFeedMacroEmitter exits loop when _shutdown=True is set.

    REQ-83-G1: The emitter handles SIGTERM by completing the current cycle
    and exiting. We simulate this by setting _shutdown=True directly
    (signal delivery in tests is unreliable cross-platform).
    """
    _setup_env()
    _clear_emitter_module()

    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter

    mock_composer = MagicMock()
    mock_envelope = MagicMock()
    mock_envelope.payload = MagicMock()
    mock_envelope.payload.items = []
    mock_envelope.provenance = {
        "agent_id": "vm107.macro_emitter",
        "prompt_version": "v1.0",
        "model_version": "claude-sonnet-4-5",
        "generated_at": "2026-06-04T12:00:00+00:00",
        "registry_snapshot_hash": "a" * 64,
    }
    mock_composer.compose.return_value = mock_envelope

    mock_state = MagicMock()
    mock_state.detect_state.return_value = "OPEN"
    mock_writer = MagicMock()
    mock_writer.write.return_value = 1
    mock_cache = MagicMock()
    mock_cache.read.return_value = None
    mock_redis = MagicMock()

    # pubsub that never returns a message
    mock_pubsub = MagicMock()
    mock_pubsub.get_message.return_value = None
    mock_pubsub.subscribe = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub

    emitter = IntelligenceFeedMacroEmitter(
        composer=mock_composer,
        state_client=mock_state,
        snapshot_writer=mock_writer,
        snapshot_cache=mock_cache,
        redis_client=mock_redis,
    )

    # Simulate SIGTERM: set _shutdown after a tiny delay so the loop exits
    def trigger_shutdown():
        time.sleep(0.15)
        emitter._shutdown = True

    # Patch _sleep_with_interrupts to check shutdown flag immediately
    original_sleep = emitter._sleep_with_interrupts

    def fast_sleep(cadence_sec, pubsub):
        """Shortened sleep: just checks for shutdown immediately."""
        emitter._shutdown = True
        return None

    emitter._sleep_with_interrupts = fast_sleep

    # Run in a thread so we don't block forever on test failure
    result = {"completed": False, "error": None}

    def run_emitter():
        try:
            emitter.run()
            result["completed"] = True
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=run_emitter, daemon=True)
    thread.start()
    thread.join(timeout=3.0)

    assert not thread.is_alive(), "Emitter loop did not exit within 3s after _shutdown=True"
    assert result["completed"] is True, f"Emitter errored: {result['error']}"
    assert mock_composer.compose.call_count >= 1, "Emitter must have run at least one cycle"
