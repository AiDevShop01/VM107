"""Phase 83 Plan 10 — SnapshotHTTPWriter + SnapshotRedisCache unit tests.

Tests services/snapshot_writer.py (VM107 side).
No Django dependency — all external I/O is mocked.
"""
import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


def _clear_snapshot_writer_module():
    """Force module reload to pick up env var changes."""
    for mod in list(sys.modules.keys()):
        if "snapshot_writer" in mod:
            del sys.modules[mod]


@pytest.mark.phase83
def test_SnapshotHTTPWriter_calls_endpoint_with_jwt():
    """SnapshotHTTPWriter.write calls POST with Authorization header + correct URL.

    Plan 10 Task 1 — Green test 5.
    """
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-service-jwt"
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"

    _clear_snapshot_writer_module()

    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": 42}
        mock_post.return_value = mock_resp

        from services.snapshot_writer import SnapshotHTTPWriter

        envelope = MagicMock()
        envelope.model_dump.return_value = {"items": [], "state": "OPEN"}
        envelope.provenance = {
            "registry_snapshot_hash": "h" * 64,
            "prompt_version": "v1.0",
            "model_version": "claude-sonnet-4-5",
            "generated_at": "2026-06-04T12:00:00+00:00",
        }

        writer = SnapshotHTTPWriter(
            url="http://vm100-backend:8000",
            jwt="test-service-jwt",
        )
        result = writer.write(envelope, state="OPEN", refresh_reason="cadence")
        assert result == 42

        assert mock_post.called
        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "Authorization" in headers, f"Expected Authorization header, got: {headers}"
        assert "Bearer test-service-jwt" in headers["Authorization"]

        called_url = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("url", "")
        assert "snapshots/macro" in called_url, f"Expected snapshots/macro in URL, got: {called_url}"


@pytest.mark.phase83
def test_SnapshotHTTPWriter_raises_on_4xx():
    """SnapshotHTTPWriter raises httpx.HTTPStatusError on non-2xx response.

    Plan 10: caller (emitter loop) catches this for Tier-3 degradation.
    """
    import httpx

    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-service-jwt"
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"

    _clear_snapshot_writer_module()

    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_resp
        )
        mock_post.return_value = mock_resp

        from services.snapshot_writer import SnapshotHTTPWriter

        envelope = MagicMock()
        envelope.model_dump.return_value = {}
        envelope.provenance = {}

        writer = SnapshotHTTPWriter(url="http://vm100-backend:8000", jwt="test-jwt")
        with pytest.raises(httpx.HTTPStatusError):
            writer.write(envelope, state="OPEN", refresh_reason="cadence")


@pytest.mark.phase83
def test_SnapshotRedisCache_write_then_read_round_trip():
    """SnapshotRedisCache.write then .read returns the same dict.

    Plan 10 Task 1 — Green test 6.
    """
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-service-jwt"
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"

    _clear_snapshot_writer_module()

    try:
        import fakeredis
        fake_client = fakeredis.FakeRedis()
    except ImportError:
        pytest.skip("fakeredis not installed — install with pip install fakeredis")

    from services.snapshot_writer import SnapshotRedisCache

    envelope = MagicMock()
    payload_dict = {"items": [{"event_id": "CPI-001"}], "state": "OPEN", "degraded": False}
    envelope.model_dump.return_value = payload_dict

    cache = SnapshotRedisCache(url="redis://localhost:6379/0", ttl_sec=60)
    cache._client = fake_client  # inject fakeredis

    cache.write(envelope, state="OPEN")
    result = cache.read(state="OPEN")
    assert result is not None
    assert result == payload_dict


@pytest.mark.phase83
def test_SnapshotRedisCache_TTL_60s():
    """SnapshotRedisCache.write sets key TTL close to 60s.

    Plan 10 Task 1 — Green test 7.
    Asserts TTL is between 58s and 61s (2s tolerance for timing).
    """
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-service-jwt"
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"

    _clear_snapshot_writer_module()

    try:
        import fakeredis
        fake_client = fakeredis.FakeRedis()
    except ImportError:
        pytest.skip("fakeredis not installed — install with pip install fakeredis")

    from services.snapshot_writer import SnapshotRedisCache

    envelope = MagicMock()
    envelope.model_dump.return_value = {"items": [], "state": "PRE"}

    cache = SnapshotRedisCache(url="redis://localhost:6379/0", ttl_sec=60)
    cache._client = fake_client

    cache.write(envelope, state="PRE")
    ttl = fake_client.ttl("macro_emitter:latest:PRE")
    assert 58 <= ttl <= 61, f"Expected TTL ~60s, got {ttl}"


@pytest.mark.phase83
def test_SnapshotRedisCache_read_returns_none_on_missing_key():
    """SnapshotRedisCache.read returns None when key doesn't exist."""
    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-service-jwt"
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"

    _clear_snapshot_writer_module()

    try:
        import fakeredis
        fake_client = fakeredis.FakeRedis()
    except ImportError:
        pytest.skip("fakeredis not installed — install with pip install fakeredis")

    from services.snapshot_writer import SnapshotRedisCache

    cache = SnapshotRedisCache(url="redis://localhost:6379/0", ttl_sec=60)
    cache._client = fake_client

    result = cache.read(state="ACTIVE_SUPERVISION")
    assert result is None


@pytest.mark.phase83
def test_SnapshotRedisCache_write_swallows_redis_error():
    """SnapshotRedisCache.write logs warning and returns gracefully on Redis error.

    G2 hot path is best-effort — Postgres is the truth store.
    """
    import redis

    os.environ["MACRO_EMITTER_SNAPSHOT_URL"] = "http://vm100-backend:8000"
    os.environ["VM107_SERVICE_JWT"] = "test-service-jwt"
    os.environ["MACRO_EMITTER_REDIS_URL"] = "redis://localhost:6379/0"

    _clear_snapshot_writer_module()

    from services.snapshot_writer import SnapshotRedisCache

    envelope = MagicMock()
    envelope.model_dump.return_value = {"items": []}

    cache = SnapshotRedisCache(url="redis://localhost:6379/0", ttl_sec=60)
    mock_client = MagicMock()
    mock_client.setex.side_effect = redis.RedisError("connection refused")
    cache._client = mock_client

    # Should NOT raise — degrades gracefully
    cache.write(envelope, state="OPEN")
