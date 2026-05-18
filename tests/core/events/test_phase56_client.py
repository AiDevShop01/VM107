"""Phase 48 Plan 48-03 Task 3.1 — VM107-side Phase 56 emit client.

Implements REQ-48-PHASE56-CLIENT.

Behavior contract (Plan 48-03 Task 3.1):
- emit_event() POSTs to ``{VM100_INTERNAL_BASE_URL}/api/journal/internal/events/emit``.
- Missing ``VM100_INTERNAL_BASE_URL`` env var raises ``KeyError`` (no fallback).
- HTTP 2xx returns None.
- HTTP 4xx raises ``Phase56EmitError`` with the response detail (NO retry).
- HTTP 5xx raises ``Phase56EmitError`` after exactly one retry.
- ``httpx.ConnectError`` raises ``Phase56EmitError`` after exactly one retry.
- ``occurred_at`` is added to the payload at call time (UTC ISO 8601 ``Z``).
- ``causality_scope`` defaults to ``"IDEA"`` (planner decision for V1).

Env-driven config — no fallback per memory/feedback_env_driven_no_fallbacks.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_env(monkeypatch):
    """Set the required env var. Reverse-engineered to support delenv tests."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100.test:8000")
    return "http://vm100.test:8000"


@pytest.fixture
def http_response_factory():
    """Build a fake httpx.Response for the mock client."""

    def _factory(status_code: int, body: dict | None = None) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.text = "" if body is None else str(body)
        resp.json.return_value = body or {}
        return resp

    return _factory


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_emit_event_posts_to_vm100_internal_endpoint(
    fake_env, http_response_factory, monkeypatch
):
    from core.events import phase56_client

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            self.timeout = kw.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return http_response_factory(200)

    monkeypatch.setattr(phase56_client.httpx, "Client", _FakeClient)

    result = phase56_client.emit_event(
        event_type="refinement_loop_started",
        category="cognition",
        correlation_id="corr-123",
        payload={"loop_id": "loop-abc"},
    )

    assert result is None
    assert captured["url"] == "http://vm100.test:8000/api/journal/internal/events/emit"
    body = captured["json"]
    assert body["event_type"] == "refinement_loop_started"
    assert body["category"] == "cognition"
    assert body["correlation_id"] == "corr-123"
    assert body["causality_scope"] == "IDEA"  # default
    assert body["payload"] == {"loop_id": "loop-abc"}
    # occurred_at appended at call time (ISO 8601 UTC, ending in Z or +00:00)
    assert "occurred_at" in body
    parsed = datetime.fromisoformat(body["occurred_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) == timezone.utc.utcoffset(parsed)


def test_emit_event_respects_explicit_causality_scope(
    fake_env, http_response_factory, monkeypatch
):
    from core.events import phase56_client

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers=None):
            captured["json"] = json
            return http_response_factory(202)

    monkeypatch.setattr(phase56_client.httpx, "Client", _FakeClient)

    phase56_client.emit_event(
        event_type="iteration_started",
        category="cognition",
        correlation_id="corr-9",
        payload={},
        causality_scope="REFINEMENT_LOOP",
    )

    assert captured["json"]["causality_scope"] == "REFINEMENT_LOOP"


# ---------------------------------------------------------------------------
# Env-var fail-fast (no fallback)
# ---------------------------------------------------------------------------


def test_emit_event_raises_keyerror_when_env_missing(monkeypatch):
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)
    from core.events import phase56_client

    with pytest.raises(KeyError):
        phase56_client.emit_event(
            event_type="iteration_started",
            category="cognition",
            correlation_id="corr-1",
            payload={},
        )


# ---------------------------------------------------------------------------
# 4xx — no retry, raise immediately
# ---------------------------------------------------------------------------


def test_emit_event_raises_on_4xx_without_retry(
    fake_env, http_response_factory, monkeypatch
):
    from core.events import phase56_client

    post_call_count = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            post_call_count["n"] += 1
            return http_response_factory(400, {"detail": "bad body"})

    monkeypatch.setattr(phase56_client.httpx, "Client", _FakeClient)

    with pytest.raises(phase56_client.Phase56EmitError):
        phase56_client.emit_event(
            event_type="iteration_started",
            category="cognition",
            correlation_id="corr-1",
            payload={},
        )

    assert post_call_count["n"] == 1, "4xx must NOT retry"


# ---------------------------------------------------------------------------
# 5xx — retry once then raise
# ---------------------------------------------------------------------------


def test_emit_event_retries_once_on_5xx_then_raises(
    fake_env, http_response_factory, monkeypatch
):
    from core.events import phase56_client

    post_call_count = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            post_call_count["n"] += 1
            return http_response_factory(500, {"detail": "server"})

    monkeypatch.setattr(phase56_client.httpx, "Client", _FakeClient)

    with pytest.raises(phase56_client.Phase56EmitError):
        phase56_client.emit_event(
            event_type="iteration_started",
            category="cognition",
            correlation_id="corr-1",
            payload={},
        )

    assert post_call_count["n"] == 2, "5xx must retry exactly once"


# ---------------------------------------------------------------------------
# ConnectError — retry once then raise
# ---------------------------------------------------------------------------


def test_emit_event_retries_once_on_connect_error_then_raises(
    fake_env, monkeypatch
):
    from core.events import phase56_client

    post_call_count = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            post_call_count["n"] += 1
            raise httpx.ConnectError("dial tcp: refused")

    monkeypatch.setattr(phase56_client.httpx, "Client", _FakeClient)

    with pytest.raises(phase56_client.Phase56EmitError):
        phase56_client.emit_event(
            event_type="iteration_started",
            category="cognition",
            correlation_id="corr-1",
            payload={},
        )

    assert post_call_count["n"] == 2, "ConnectError must retry exactly once"


# ---------------------------------------------------------------------------
# Replay snapshot validation primitive (Task 3.3 — landed in same module)
# ---------------------------------------------------------------------------


def test_validate_snapshot_for_replay_raises_on_mismatch(monkeypatch):
    from core.events import phase56_client

    class _FakeRegistry:
        snapshot_hash = "current-snapshot-aaaa"

    monkeypatch.setattr(
        phase56_client.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegistry())
    )

    with pytest.raises(phase56_client.SnapshotMismatchError):
        phase56_client.validate_snapshot_for_replay("stored-snapshot-bbbb")


def test_validate_snapshot_for_replay_returns_none_on_match(monkeypatch):
    from core.events import phase56_client

    class _FakeRegistry:
        snapshot_hash = "matching-snapshot-cccc"

    monkeypatch.setattr(
        phase56_client.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegistry())
    )

    assert phase56_client.validate_snapshot_for_replay("matching-snapshot-cccc") is None


# ---------------------------------------------------------------------------
# AST guard — module must NOT contain os.getenv or os.environ.get
# ---------------------------------------------------------------------------


def test_phase56_client_uses_direct_subscript_only():
    import ast
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    src = (repo_root / "core" / "events" / "phase56_client.py").read_text()
    tree = ast.parse(src)

    # No call to os.getenv or os.environ.get
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # os.getenv(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                pytest.fail(f"phase56_client.py contains os.getenv at line {node.lineno}")
            # os.environ.get(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
            ):
                pytest.fail(
                    f"phase56_client.py contains os.environ.get at line {node.lineno}"
                )

    # Direct subscript must appear
    assert 'os.environ["VM100_INTERNAL_BASE_URL"]' in src, (
        "phase56_client.py must read env via direct subscript"
    )
