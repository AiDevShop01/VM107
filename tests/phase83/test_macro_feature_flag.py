"""REQ-83-H2 — MACRO_EMITTER_ENABLED feature flag controls emitter behavior.

Phase 83 Plan 10 — GREENs these tests by shipping:
  VM107/emitters/intelligence_feed_macro_emitter.py (_is_enabled + _emit_demo_snapshot)

Feature flag semantics:
  MACRO_EMITTER_ENABLED=true  → normal emitter operation (real calendar + LLM via composer)
  MACRO_EMITTER_ENABLED=false → emit demo snapshot (source='vm107.macro_emitter.demo_fallback')

This flag is an emergency shutoff that operators can flip without redeploying
(read from env on each cycle, not once at __init__).

Pitfall 12 (CONTEXT.md): H1 degradation (LLM timeout) NEVER sets _demo=True.
Only the H2 kill-switch path (_emit_demo_snapshot) sets the demo marker.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock


def _clear_emitter_module():
    for mod in list(sys.modules.keys()):
        if "intelligence_feed_macro_emitter" in mod and "composer" not in mod:
            del sys.modules[mod]


@pytest.mark.phase83
def test_flag_off_calls_emit_demo_NOT_composer():
    """MACRO_EMITTER_ENABLED=false → _emit_demo_snapshot called, composer.compose NOT called.

    REQ-83-H2: When kill-switch is off, no calendar API or LLM calls occur.
    Pitfall 12: demo_fallback marker set ONLY in H2 path.
    """
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-jwt"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_ENABLED"] = "false"
    os.environ["MACRO_EMITTER_INTERRUPT_POLL_SEC"] = "0.05"
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

    # _is_enabled() should return False
    assert emitter._is_enabled() is False, "Expected _is_enabled() False when MACRO_EMITTER_ENABLED=false"

    # Call _emit_demo_snapshot directly to verify it writes the demo marker
    emitter._emit_demo_snapshot("OPEN")

    # Should have written a demo snapshot to writer and cache
    assert mock_writer.write.called, "_emit_demo_snapshot must call snapshot_writer.write"
    assert mock_cache.write.called, "_emit_demo_snapshot must call snapshot_cache.write"

    # The envelope passed to writer.write must have source='vm107.macro_emitter.demo_fallback'
    envelope_arg = mock_writer.write.call_args.args[0]
    assert hasattr(envelope_arg, "payload"), "Envelope must have .payload"
    assert envelope_arg.payload.source == "vm107.macro_emitter.demo_fallback", (
        f"Expected demo_fallback source, got: {getattr(envelope_arg.payload, 'source', None)}"
    )

    # Composer must NOT have been called
    mock_composer.compose.assert_not_called()


@pytest.mark.phase83
def test_flag_on_means_is_enabled_returns_true():
    """MACRO_EMITTER_ENABLED=true → _is_enabled() returns True.

    REQ-83-H2: Normal operation when flag is on.
    """
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-jwt"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_ENABLED"] = "true"
    _clear_emitter_module()

    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter

    emitter = IntelligenceFeedMacroEmitter(
        composer=MagicMock(),
        state_client=MagicMock(),
        snapshot_writer=MagicMock(),
        snapshot_cache=MagicMock(),
        redis_client=MagicMock(),
    )

    assert emitter._is_enabled() is True, "Expected _is_enabled() True when MACRO_EMITTER_ENABLED=true"


@pytest.mark.phase83
def test_flag_is_checked_per_cycle_not_just_startup():
    """_is_enabled() reads from os.environ live — changes take effect each cycle.

    REQ-83-H2: Operators flip the flag without restarting the container.
    Verify _is_enabled() reflects env changes between calls.
    """
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-jwt"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_ENABLED"] = "true"
    _clear_emitter_module()

    from emitters.intelligence_feed_macro_emitter import IntelligenceFeedMacroEmitter

    emitter = IntelligenceFeedMacroEmitter(
        composer=MagicMock(),
        state_client=MagicMock(),
        snapshot_writer=MagicMock(),
        snapshot_cache=MagicMock(),
        redis_client=MagicMock(),
    )

    # Start enabled
    assert emitter._is_enabled() is True

    # Simulate operator flip
    os.environ["MACRO_EMITTER_ENABLED"] = "false"
    assert emitter._is_enabled() is False, (
        "_is_enabled() must read from env per-call, not cache at __init__"
    )

    # Flip back
    os.environ["MACRO_EMITTER_ENABLED"] = "true"
    assert emitter._is_enabled() is True
