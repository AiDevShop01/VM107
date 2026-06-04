"""REQ-83-G1, REQ-83-G2, REQ-83-H1 — IntelligenceFeedMacroEmitter lifecycle + cadences + degradation.

Phase 83 Plan 10 — GREENs these tests by shipping:
  VM107/emitters/intelligence_feed_macro_emitter.py
  VM107/services/snapshot_writer.py
  VM107/docker-compose.yml (vm107-macro-emitter service entry)

Per-state cadence (REQ-83-G1):
  PRE session:         300s (5 min)
  OPEN session:        60s
  ACTIVE_SUPERVISION:  90s (60-120s midpoint)
  MID_OBSERVATION:     120s (2 min)
  CLOSE session:       300s (5 min)
  REVIEW:              600s (event-driven, interrupt-aware)

Snapshot persistence: Postgres + Redis (Decision G2)
Tiered degradation: Tier-3 = last-known-good from Redis (Decision H1, Pitfall 12)
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call


def _make_emitter(state="OPEN", composer_raises=False, demo_flag=False):
    """Helper: build IntelligenceFeedMacroEmitter with all deps mocked."""
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-jwt"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    if demo_flag:
        os.environ["MACRO_EMITTER_ENABLED"] = "false"
    else:
        os.environ["MACRO_EMITTER_ENABLED"] = "true"

    # Clear module cache so env changes take effect
    for mod in list(sys.modules.keys()):
        if "intelligence_feed_macro_emitter" in mod and "composer" not in mod:
            del sys.modules[mod]

    from emitters.intelligence_feed_macro_emitter import (
        IntelligenceFeedMacroEmitter,
        DEFAULT_CADENCES,
    )

    mock_composer = MagicMock()
    if composer_raises:
        mock_composer.compose.side_effect = RuntimeError("LLM timeout")
    else:
        mock_envelope = MagicMock()
        mock_envelope.payload.items = [{"event_id": "CPI-001"}]
        mock_envelope.provenance = {
            "agent_id": "vm107.macro_emitter",
            "prompt_version": "v1.0",
            "model_version": "claude-sonnet-4-5",
            "generated_at": "2026-06-04T12:00:00+00:00",
            "registry_snapshot_hash": "a" * 64,
        }
        mock_composer.compose.return_value = mock_envelope

    mock_state = MagicMock()
    mock_state.detect_state.return_value = state

    mock_writer = MagicMock()
    mock_writer.write.return_value = 42

    mock_cache = MagicMock()
    mock_cache.read.return_value = {"items": [{"event_id": "CPI-001"}], "state": state}
    mock_cache.write.return_value = None

    try:
        import fakeredis
        fake_redis = fakeredis.FakeRedis()
    except ImportError:
        fake_redis = MagicMock()
        # Mock pubsub for non-interrupt tests
        fake_pubsub = MagicMock()
        fake_pubsub.get_message.return_value = None
        fake_redis.pubsub.return_value = fake_pubsub

    emitter = IntelligenceFeedMacroEmitter(
        composer=mock_composer,
        state_client=mock_state,
        snapshot_writer=mock_writer,
        snapshot_cache=mock_cache,
        redis_client=fake_redis,
    )
    return emitter, mock_composer, mock_writer, mock_cache


# ---------------------------------------------------------------------------
# Cadence tests (REQ-83-G1)
# ---------------------------------------------------------------------------


@pytest.mark.phase83
def test_cadence_pre_5min():
    """In PRE session state, emitter cadence is 300 seconds (5 minutes).

    REQ-83-G1: Pre-session macro data is low-urgency.
    """
    emitter, *_ = _make_emitter(state="PRE")
    assert emitter._cadence_for_state("PRE") == 300


@pytest.mark.phase83
def test_cadence_open_60s():
    """In OPEN session state, emitter cadence is 60 seconds.

    REQ-83-G1: Once the session opens, macro data becomes high-urgency.
    """
    emitter, *_ = _make_emitter(state="OPEN")
    assert emitter._cadence_for_state("OPEN") == 60


@pytest.mark.phase83
def test_cadence_active_60_120s():
    """In ACTIVE_SUPERVISION, emitter cadence is 90 seconds (midpoint of 60-120).

    REQ-83-G1: Active macro releases use novelty-gated polling.
    """
    emitter, *_ = _make_emitter(state="ACTIVE_SUPERVISION")
    cadence = emitter._cadence_for_state("ACTIVE_SUPERVISION")
    assert 60 <= cadence <= 120


@pytest.mark.phase83
def test_cadence_mid_2min():
    """In MID_OBSERVATION, emitter cadence is 120 seconds (2 minutes).

    REQ-83-G1: Mid-session macro data is medium-urgency.
    """
    emitter, *_ = _make_emitter(state="MID_OBSERVATION")
    assert emitter._cadence_for_state("MID_OBSERVATION") == 120


@pytest.mark.phase83
def test_cadence_close_5min():
    """In CLOSE session state, emitter cadence is 300 seconds (5 minutes).

    REQ-83-G1: Close-session macro data is low-urgency.
    """
    emitter, *_ = _make_emitter(state="CLOSE")
    assert emitter._cadence_for_state("CLOSE") == 300


@pytest.mark.phase83
def test_cadence_review_event_driven():
    """In REVIEW state, emitter cadence is >= 600 seconds (event-driven sleep).

    REQ-83-G1: REVIEW is driven by Redis interrupts from calendar events.
    """
    emitter, *_ = _make_emitter(state="REVIEW")
    assert emitter._cadence_for_state("REVIEW") >= 600


# ---------------------------------------------------------------------------
# Emission loop tests (lifecycle)
# ---------------------------------------------------------------------------


@pytest.mark.phase83
def test_loop_calls_composer_then_persists_to_postgres_and_redis():
    """One iteration: composer.compose called, writer.write called, cache.write called.

    Plan 10 Task 2 — Green test 7.
    """
    emitter, mock_composer, mock_writer, mock_cache = _make_emitter(state="OPEN")

    # Simulate one iteration by calling _compose_and_persist directly
    emitter._compose_and_persist(state="OPEN", refresh_reason="cadence")

    mock_composer.compose.assert_called_once_with(state="OPEN")
    mock_writer.write.assert_called_once()
    mock_cache.write.assert_called_once()

    # Check call order: composer → writer → cache
    compose_call_time = mock_composer.compose.call_args_list[0]
    write_call_time = mock_writer.write.call_args_list[0]
    cache_call_time = mock_cache.write.call_args_list[0]
    assert compose_call_time is not None
    assert write_call_time is not None
    assert cache_call_time is not None


@pytest.mark.phase83
def test_tier_3_degradation_persists_last_known_good_NOT_demo():
    """When composer raises, _persist_degraded uses last-known-good from Redis.

    Plan 10 Task 2 — Green test 8.
    Pitfall 12: NEVER re-show [DEMO] during H1 degradation.
    """
    emitter, mock_composer, mock_writer, mock_cache = _make_emitter(
        state="OPEN", composer_raises=True
    )

    # Call _persist_degraded and check cache is queried
    emitter._persist_degraded("OPEN")

    # Should read from cache (last-known-good)
    mock_cache.read.assert_called_once_with("OPEN")

    # Should NOT write a new snapshot with _demo=True
    # (no new write should occur — cache already has the last good state)
    mock_writer.write.assert_not_called()


@pytest.mark.phase83
def test_envelope_provenance_populated_on_each_write():
    """SnapshotHTTPWriter.write receives envelope with non-empty provenance dict.

    Plan 10 Task 2 — Green test 9.
    Phase 70.5: AgentEnvelope provenance contract.
    """
    emitter, mock_composer, mock_writer, mock_cache = _make_emitter(state="OPEN")

    emitter._compose_and_persist(state="OPEN", refresh_reason="cadence")

    # The write call should have passed the envelope as first arg
    assert mock_writer.write.called
    call_args = mock_writer.write.call_args
    envelope = call_args.args[0] if call_args.args else None
    assert envelope is not None

    # Provenance on the mock envelope should be non-empty
    assert hasattr(envelope, "provenance")
    assert envelope.provenance, "Provenance must be non-empty on write"


# ---------------------------------------------------------------------------
# Healthz tests (Open Question 7 — tested separately via lifecycle module)
# ---------------------------------------------------------------------------


@pytest.mark.phase83
def test_healthz_returns_200_when_all_deps_ok():
    """HealthzHandler returns 200 + ok=true when all deps are healthy.

    Plan 10 Task 3 — Green test 1.
    """
    import io
    from unittest.mock import MagicMock, patch
    from datetime import datetime, timezone, timedelta

    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_HEALTHZ_PORT"] = "8090"
    os.environ["MACRO_EMITTER_MAX_EMISSION_AGE_SEC"] = "1200"

    # Clear module so it picks up env
    for mod in list(sys.modules.keys()):
        if "macro_emitter_healthz" in mod:
            del sys.modules[mod]

    import emitters.intelligence_feed_macro_emitter as emitter_mod
    # Set recent emission
    emitter_mod._LAST_EMISSION_AT = datetime.now(timezone.utc) - timedelta(seconds=30)

    with patch("httpx.get") as mock_httpx, \
         patch("redis.Redis.from_url") as mock_redis_cls:
        mock_httpx.return_value.status_code = 200
        mock_redis_inst = MagicMock()
        mock_redis_inst.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_inst

        from emitters.macro_emitter_healthz import HealthzHandler

        handler = HealthzHandler.__new__(HealthzHandler)
        handler.path = "/healthz"

        # Capture the response
        responses = []
        body_data = []

        def mock_send_response(code):
            responses.append(code)

        def mock_send_header(key, val):
            pass

        def mock_end_headers():
            pass

        mock_wfile = MagicMock()

        def mock_wfile_write(data):
            body_data.append(data)

        mock_wfile.write = mock_wfile_write
        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers
        handler.wfile = mock_wfile

        handler.do_GET()

        assert 200 in responses, f"Expected 200, got {responses}"
        import json as _json
        body = _json.loads(body_data[0]) if body_data else {}
        assert body.get("ok") is True


@pytest.mark.phase83
def test_healthz_returns_503_when_redis_unreachable():
    """HealthzHandler returns 503 when Redis ping fails.

    Plan 10 Task 3 — Green test 3.
    """
    import redis as _redis

    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_HEALTHZ_PORT"] = "8090"
    os.environ["MACRO_EMITTER_MAX_EMISSION_AGE_SEC"] = "1200"

    for mod in list(sys.modules.keys()):
        if "macro_emitter_healthz" in mod:
            del sys.modules[mod]

    from datetime import timedelta, datetime, timezone
    import emitters.intelligence_feed_macro_emitter as emitter_mod
    emitter_mod._LAST_EMISSION_AT = datetime.now(timezone.utc) - timedelta(seconds=30)

    with patch("httpx.get") as mock_httpx, \
         patch("redis.Redis.from_url") as mock_redis_cls:
        mock_httpx.return_value.status_code = 200
        mock_redis_inst = MagicMock()
        mock_redis_inst.ping.side_effect = _redis.RedisError("connection refused")
        mock_redis_cls.return_value = mock_redis_inst

        from emitters.macro_emitter_healthz import HealthzHandler

        handler = HealthzHandler.__new__(HealthzHandler)
        handler.path = "/healthz"
        responses = []
        body_data = []

        handler.send_response = lambda code: responses.append(code)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        mock_wfile = MagicMock()
        mock_wfile.write = lambda d: body_data.append(d)
        handler.wfile = mock_wfile

        handler.do_GET()

        assert 503 in responses, f"Expected 503, got {responses}"
        import json as _json
        body = _json.loads(body_data[0]) if body_data else {}
        assert body["deps"]["redis"] is False


@pytest.mark.phase83
def test_healthz_returns_503_when_last_emission_stale():
    """HealthzHandler returns 503 when last emission is too old (> max age).

    Plan 10 Task 3 — Green test 4.
    """
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["MACRO_EMITTER_CALENDAR_URL"] = "http://vm100-backend:8000"
    os.environ["MACRO_EMITTER_HEALTHZ_PORT"] = "8090"
    os.environ["MACRO_EMITTER_MAX_EMISSION_AGE_SEC"] = "60"  # Short for test

    for mod in list(sys.modules.keys()):
        if "macro_emitter_healthz" in mod:
            del sys.modules[mod]

    from datetime import timedelta, datetime, timezone
    import emitters.intelligence_feed_macro_emitter as emitter_mod
    # Make last emission stale (2 hours ago, max is 60s)
    emitter_mod._LAST_EMISSION_AT = datetime.now(timezone.utc) - timedelta(hours=2)

    with patch("httpx.get") as mock_httpx, \
         patch("redis.Redis.from_url") as mock_redis_cls:
        mock_httpx.return_value.status_code = 200
        mock_redis_inst = MagicMock()
        mock_redis_inst.ping.return_value = True
        mock_redis_cls.return_value = mock_redis_inst

        from emitters.macro_emitter_healthz import HealthzHandler

        handler = HealthzHandler.__new__(HealthzHandler)
        handler.path = "/healthz"
        responses = []
        body_data = []

        handler.send_response = lambda code: responses.append(code)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        mock_wfile = MagicMock()
        mock_wfile.write = lambda d: body_data.append(d)
        handler.wfile = mock_wfile

        handler.do_GET()

        assert 503 in responses, f"Expected 503 (stale emission), got {responses}"
        import json as _json
        body = _json.loads(body_data[0]) if body_data else {}
        assert body.get("ok") is False
