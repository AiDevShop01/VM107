"""Tests for VM107 lookup_replay_artifact tool — CONTEXT §18.

Graduated in 59-07: xfail stubs replaced with proper mocked tests.

Tests use unittest.mock to mock httpx.Client so no live VM100 connection
is required. Each test verifies:
  - 200 → ReplayArtifactMeta typed return
  - 404 → ToolError(code='not_found')
  - 503 → ToolError(code='vm100_degraded')
  - transport error → ToolError(code='vm100_unavailable')
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Canned response data
# ---------------------------------------------------------------------------

_EXEC_ID = uuid4()
_ARTIFACT_ID = uuid4()

_VALID_META = {
    "schema_version": "1.0",
    "id": str(_ARTIFACT_ID),
    "execution_id": str(_EXEC_ID),
    "artifact_type": "narration_v1",
    "truth_mode": "HISTORICAL",
    "generated_reason": "AUTO",
    "replay_version": 1,
    "replay_template_version": "1.0.0",
    "reconstruction_service_version": "1.0.0",
    "ruleset_version": "1.0.0",
    "generated_at": "2026-05-11T10:00:00+00:00",
    "line_count": 5,
    "frame_count": 3,
}


def _make_mock_response(status_code: int, body: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLookupReplayArtifact200:
    """200 path: valid ReplayArtifactMeta returned."""

    def test_returns_typed_meta(self):
        """lookup_replay_artifact returns ReplayArtifactMeta on 200."""
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact
        from fingpt_core.contracts.replay import ReplayArtifactMeta

        mock_resp = _make_mock_response(200, _VALID_META)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(_EXEC_ID)

        assert isinstance(result, ReplayArtifactMeta)
        assert result.execution_id == _EXEC_ID
        assert result.replay_version == 1

    def test_latest_version_when_none(self):
        """lookup_replay_artifact with replay_version=None returns the artifact."""
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact
        from fingpt_core.contracts.replay import ReplayArtifactMeta

        mock_resp = _make_mock_response(200, _VALID_META)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(_EXEC_ID, replay_version=None)

        assert isinstance(result, ReplayArtifactMeta)
        assert result.replay_version >= 1

    def test_specific_version_param_passed(self):
        """replay_version param is forwarded as query param to VM100."""
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact

        mock_resp = _make_mock_response(200, _VALID_META)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            lookup_replay_artifact(_EXEC_ID, replay_version=2)

        call_kwargs = mock_client.get.call_args
        params = call_kwargs[1].get("params", {}) if call_kwargs[1] else {}
        assert params.get("replay_version") == 2


class TestLookupReplayArtifactErrors:
    """Error-path tests: 404/503/504/transport → ToolError."""

    def test_404_returns_tool_error_not_found(self):
        """404 → ToolError(code='not_found'); does NOT raise."""
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact, ToolError

        mock_resp = _make_mock_response(404)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(uuid4())

        assert isinstance(result, ToolError)
        assert result.code == "not_found"

    def test_503_returns_tool_error_degraded(self):
        """503 → ToolError(code='vm100_degraded'); does NOT raise."""
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact, ToolError

        mock_resp = _make_mock_response(503)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(uuid4())

        assert isinstance(result, ToolError)
        assert result.code == "vm100_degraded"

    def test_504_returns_tool_error_degraded(self):
        """504 → ToolError(code='vm100_degraded'); does NOT raise."""
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact, ToolError

        mock_resp = _make_mock_response(504)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(uuid4())

        assert isinstance(result, ToolError)
        assert result.code == "vm100_degraded"

    def test_connect_error_returns_tool_error_unavailable(self):
        """httpx.ConnectError → ToolError(code='vm100_unavailable'); does NOT raise."""
        import httpx
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact, ToolError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(uuid4())

        assert isinstance(result, ToolError)
        assert result.code == "vm100_unavailable"

    def test_timeout_returns_tool_error_unavailable(self):
        """httpx.TimeoutException → ToolError(code='vm100_unavailable'); does NOT raise."""
        import httpx
        from tools.replay.lookup_replay_artifact import lookup_replay_artifact, ToolError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        with patch("tools.replay.lookup_replay_artifact.httpx.Client", return_value=mock_client):
            result = lookup_replay_artifact(uuid4())

        assert isinstance(result, ToolError)
        assert result.code == "vm100_unavailable"
