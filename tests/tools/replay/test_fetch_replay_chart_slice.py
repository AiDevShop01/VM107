"""Tests for VM107 fetch_replay_chart_slice tool — CONTEXT §13, §18.

Returns a ChartSlice centered on a given datetime.
Chart data is fetched separately from frame data (CONTEXT §13).
Graduates in 59-07.
"""
import pytest
from datetime import datetime, timezone


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_fetch_replay_chart_slice_returns_chart_slice():
    """fetch_replay_chart_slice returns a ChartSlice with bars."""
    from vm107.tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
    now = datetime.now(tz=timezone.utc)
    result = fetch_replay_chart_slice(
        instrument="EURUSD",
        timeframe="H4",
        center_at=now.isoformat(),
        bars_around=50,
    )
    assert result is not None
    assert hasattr(result, "bars")


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_fetch_replay_chart_slice_center_at():
    """ChartSlice center_at is close to the requested datetime."""
    from vm107.tools.replay.fetch_replay_chart_slice import fetch_replay_chart_slice
    now = datetime.now(tz=timezone.utc)
    result = fetch_replay_chart_slice(
        instrument="EURUSD",
        timeframe="H4",
        center_at=now.isoformat(),
        bars_around=50,
    )
    assert result.center_at is not None


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_fetch_replay_chart_slice_no_ohlc_in_frame():
    """ReplayFrame.chart_anchor is a reference — not the OHLC payload itself."""
    from vm107.tools.replay.fetch_replay_frame import fetch_replay_frame
    from uuid import uuid4
    frame = fetch_replay_frame(execution_id=str(uuid4()), frame_index=0)
    # chart_anchor is ChartAnchor (reference), not ChartSlice (data)
    assert not hasattr(frame.chart_anchor, "bars"), (
        "frame.chart_anchor must be ChartAnchor (reference), not ChartSlice (data payload)"
    )
