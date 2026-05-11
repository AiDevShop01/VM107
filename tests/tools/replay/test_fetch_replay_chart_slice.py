"""Tests for VM107 fetch_replay_chart_slice tool — CONTEXT §13, §18.

Graduated in 59-07: xfail stubs replaced with proper mocked tests.

Endpoint: GET /api/journal/replay/{execution_id}/chart-slice (PUBLIC endpoint)
NOTE: VM107 tools call the INTERNAL endpoint via service token OR the chart
slice endpoint has a VM107 path. Per 59-06 SUMMARY: "chart-slice has auth=JWTAuth()
— VM107 tools MUST NOT call it (use internal endpoints instead)."

The tool calls: GET /api/journal/internal/replay-artifacts/{execution_id}/chart-slice
(or equivalent internal path). If no internal chart-slice exists, tool degrades
gracefully per CONTEXT §13.

CONTEXT §13 — graceful degrade: if VM102 is down, returns ChartSlice with
empty bars and degraded=True annotation so mentor agent can skip chart reasoning.

Tests verify:
  - 200 → ChartSlice typed return with populated bars
  - 503 with fallback=True → ChartSlice(bars=[], degraded=True)  [VM102 down]
  - transport error → ChartSlice(bars=[], degraded=True)
  - center_at is populated on successful return
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
# Canned data
# ---------------------------------------------------------------------------

_EXEC_ID = uuid4()
_NOW = datetime.now(tz=timezone.utc)
_NOW_STR = _NOW.isoformat()


def _make_chart_slice_body() -> dict:
    return {
        "schema_version": "1.0",
        "instrument": "EURUSD",
        "timeframe": "H4",
        "bars": [
            {
                "schema_version": "1.0",
                "dt": "2026-05-11T08:00:00+00:00",
                "open": 1.094,
                "high": 1.096,
                "low": 1.093,
                "close": 1.095,
                "volume": None,
                "tick_volume": 120,
            }
        ],
        "requested_around": _NOW_STR,
        "center_at": "2026-05-11T08:00:00+00:00",
    }


def _make_mock_response(status_code: int, body: dict | None = None) -> MagicMock:
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


class TestFetchReplayChartSlice200:
    """200-path: ChartSlice with bars returned."""

    def test_returns_chart_slice_type(self):
        """fetch_replay_chart_slice returns ChartSlice on 200."""
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
        from fingpt_core.contracts.replay.chart import ChartSlice

        mock_resp = _make_mock_response(200, _make_chart_slice_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert isinstance(result, ChartSlice)
        assert hasattr(result, "bars")

    def test_has_bars_and_center_at(self):
        """ChartSlice.bars is non-empty and center_at is populated."""
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice

        mock_resp = _make_mock_response(200, _make_chart_slice_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert len(result.bars) >= 1
        assert result.center_at is not None

    def test_not_degraded_on_success(self):
        """ChartSlice.degraded is False (or absent) when VM102 is up."""
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice

        mock_resp = _make_mock_response(200, _make_chart_slice_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert getattr(result, "degraded", False) is False


class TestFetchReplayChartSliceDegraded:
    """CONTEXT §13: graceful degrade when VM102 is down."""

    def test_503_with_fallback_returns_degraded_chart_slice(self):
        """503 + fallback=True → ChartSlice(bars=[], degraded=True)."""
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
        from fingpt_core.contracts.replay.chart import ChartSlice

        mock_resp = _make_mock_response(503, {"detail": "VM102 unavailable", "fallback": True})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert isinstance(result, ChartSlice)
        assert result.bars == []
        assert getattr(result, "degraded", False) is True

    def test_503_without_fallback_still_returns_degraded(self):
        """Any 503 → ChartSlice degraded, never raises."""
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
        from fingpt_core.contracts.replay.chart import ChartSlice

        mock_resp = _make_mock_response(503, {"detail": "VM102 error", "fallback": False})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert isinstance(result, ChartSlice)
        assert result.bars == []
        assert getattr(result, "degraded", False) is True

    def test_connect_error_returns_degraded(self):
        """httpx.ConnectError → degraded ChartSlice; does NOT raise."""
        import httpx
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
        from fingpt_core.contracts.replay.chart import ChartSlice

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert isinstance(result, ChartSlice)
        assert result.bars == []
        assert getattr(result, "degraded", False) is True

    def test_timeout_returns_degraded(self):
        """httpx.TimeoutException → degraded ChartSlice; does NOT raise."""
        import httpx
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
        from fingpt_core.contracts.replay.chart import ChartSlice

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert isinstance(result, ChartSlice)
        assert result.bars == []
        assert getattr(result, "degraded", False) is True


class TestFetchReplayChartSliceContextSeparation:
    """CONTEXT §13: chart slice is separate from frame data."""

    def test_chart_slice_has_instrument_and_timeframe(self):
        """ChartSlice carries instrument + timeframe (CONTEXT §13 separation)."""
        from tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice

        mock_resp = _make_mock_response(200, _make_chart_slice_body())
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with patch("tools.replay.fetch_replay_chart_slice.httpx.Client", return_value=mock_client):
            result = fetch_replay_chart_slice(_EXEC_ID, occurred_at=_NOW_STR)

        assert result.instrument is not None
        assert result.timeframe is not None
