"""Tests for VM107 fetch_replay_frame tool — CONTEXT §18.

Graduated in 59-07: xfail stubs replaced with proper mocked tests.

Endpoint: GET /api/journal/internal/replay-artifacts/{execution_id}/frames/{line_index}
Returns: ReplayFrame (Phase 59 version — NOT Phase 56's ReplayFrame)

CONTEXT §18 LOCKED rule: ReplayFrame.replay_state is non-None (state snapshot
included in every frame return so caller has full context without extra round-trip).

Tests verify:
  - 200 → ReplayFrame typed return with non-None state
  - 404 → ToolError(code='not_found')
  - 503/504 → ToolError(code='vm100_degraded')
  - transport error → ToolError(code='vm100_unavailable')
  - ChartAnchor is a reference only (no 'bars' attr) — CONTEXT §13 separation
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Canned response data
# ---------------------------------------------------------------------------

_EXEC_ID = uuid4()
_EVENT_ID = uuid4()
_NOW = "2026-05-11T10:00:00+00:00"


def _make_valid_frame_body() -> dict:
    return {
        "schema_version": "1.0",
        "frame_index": 0,
        "occurred_at": _NOW,
        "sequence_number": 1,
        "event_type": "TRADE_OPENED",
        "event_id": str(uuid4()),
        "state": {
            "schema_version": "1.0",
            "execution_id": str(_EXEC_ID),
            "reconstructed_at_t": _NOW,
            "truth_mode": "HISTORICAL",
            "lifecycle_state": {
                "schema_version": "1.0",
                "lifecycle_phase": "G2",
                "lifecycle_status": "open",
                "checklist_completed": False,
                "exit_reason": None,
            },
            "position_state": {
                "schema_version": "1.0",
                "direction": "LONG",
                "entry_price": 1.095,
                "stop_loss": None,
                "take_profit": None,
                "position_size": 1.0,
                "exit_price": None,
                "realised_pnl": None,
                "mae": None,
                "mfe": None,
            },
            "analytics_state": {
                "schema_version": "1.0",
                "ruleset_version": "1.0.0",
                "overall_quality_score": None,
                "setup_quality_score": None,
                "exit_quality_score": None,
                "risk_discipline_score": None,
            },
            "behavioral_state": {
                "schema_version": "1.0",
                "behavioral_tags": [],
                "decision_quality_indicators": [],
                "plan_adherence_score": None,
            },
            "market_context": {
                "schema_version": "1.0",
                "instrument": "EURUSD",
                "timeframe": "H4",
                "center_at": _NOW,
                "suggested_bars_around": 50,
            },
            "replay_metadata": {
                "schema_version": "1.0",
                "replay_version": 1,
                "replay_template_version": "1.0.0",
                "ruleset_version": "1.0.0",
                "reconstruction_service_version": "1.0.0",
                "reconstructed_at": _NOW,
                "truth_mode": "HISTORICAL",
            },
        },
        "narration": "Trade opened at market.",
        "chart_anchor": {
            "schema_version": "1.0",
            "instrument": "EURUSD",
            "timeframe": "H4",
            "center_at": _NOW,
            "suggested_bars": 50,
        },
        "is_waypoint": False,
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


class TestFetchReplayFrame200:
    """200-path: valid ReplayFrame returned."""

    def test_returns_typed_frame(self):
        """fetch_replay_frame returns ReplayFrame on 200."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame
        from fingpt_core.contracts.replay.frame import ReplayFrame

        mock_resp = _make_mock_response(200, _make_valid_frame_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(_EXEC_ID, occurred_at=_NOW, sequence_number=1)

        assert isinstance(result, ReplayFrame)
        assert result.frame_index == 0

    def test_frame_has_narration(self):
        """ReplayFrame.narration is populated."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame

        mock_resp = _make_mock_response(200, _make_valid_frame_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(_EXEC_ID, occurred_at=_NOW, sequence_number=1)

        assert result.narration is not None

    def test_frame_state_is_non_none(self):
        """CONTEXT §18 LOCKED: ReplayFrame.state must be non-None."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame

        mock_resp = _make_mock_response(200, _make_valid_frame_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(_EXEC_ID, occurred_at=_NOW, sequence_number=1)

        assert result.state is not None, "CONTEXT §18: state snapshot must be non-None"

    def test_chart_anchor_is_reference_not_payload(self):
        """CONTEXT §13: chart_anchor is ChartAnchor (reference), NOT ChartSlice (OHLC data)."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame
        from fingpt_core.contracts.replay.frame import ChartAnchor

        mock_resp = _make_mock_response(200, _make_valid_frame_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(_EXEC_ID, occurred_at=_NOW, sequence_number=1)

        assert isinstance(result.chart_anchor, ChartAnchor)
        assert not hasattr(result.chart_anchor, "bars"), (
            "frame.chart_anchor must be ChartAnchor (reference), not ChartSlice (data payload)"
        )


class TestFetchReplayFrameErrors:
    """Error-path tests: 404/503/504/transport → ToolError."""

    def test_404_returns_tool_error_not_found(self):
        """404 → ToolError(code='not_found'); does NOT raise."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame, ToolError

        mock_resp = _make_mock_response(404)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(uuid4(), occurred_at=_NOW, sequence_number=99999)

        assert isinstance(result, ToolError)
        assert result.code == "not_found"

    def test_503_returns_tool_error_degraded(self):
        """503 → ToolError(code='vm100_degraded'); does NOT raise."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame, ToolError

        mock_resp = _make_mock_response(503)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(uuid4(), occurred_at=_NOW, sequence_number=0)

        assert isinstance(result, ToolError)
        assert result.code == "vm100_degraded"

    def test_504_returns_tool_error_degraded(self):
        """504 → ToolError(code='vm100_degraded')."""
        from tools.replay.fetch_replay_frame import fetch_replay_frame, ToolError

        mock_resp = _make_mock_response(504)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(uuid4(), occurred_at=_NOW, sequence_number=0)

        assert isinstance(result, ToolError)
        assert result.code == "vm100_degraded"

    def test_connect_error_returns_unavailable(self):
        """httpx.ConnectError → ToolError(code='vm100_unavailable')."""
        import httpx
        from tools.replay.fetch_replay_frame import fetch_replay_frame, ToolError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(uuid4(), occurred_at=_NOW, sequence_number=0)

        assert isinstance(result, ToolError)
        assert result.code == "vm100_unavailable"

    def test_timeout_returns_unavailable(self):
        """httpx.TimeoutException → ToolError(code='vm100_unavailable')."""
        import httpx
        from tools.replay.fetch_replay_frame import fetch_replay_frame, ToolError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        with patch("tools.replay.fetch_replay_frame.httpx.Client", return_value=mock_client):
            result = fetch_replay_frame(uuid4(), occurred_at=_NOW, sequence_number=0)

        assert isinstance(result, ToolError)
        assert result.code == "vm100_unavailable"
