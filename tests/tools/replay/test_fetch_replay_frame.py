"""Tests for VM107 fetch_replay_frame tool — CONTEXT §18.

Returns a single ReplayFrame for a given (execution_id, frame_index).
Graduates in 59-07.
"""
import pytest


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_fetch_replay_frame_returns_frame():
    """fetch_replay_frame returns a ReplayFrame with frame_index."""
    from vm107.tools.replay.fetch_replay_frame import fetch_replay_frame
    from uuid import uuid4
    frame = fetch_replay_frame(execution_id=str(uuid4()), frame_index=0)
    assert frame.frame_index == 0


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_fetch_replay_frame_out_of_bounds():
    """fetch_replay_frame raises for out-of-bounds frame_index."""
    from vm107.tools.replay.fetch_replay_frame import fetch_replay_frame
    from uuid import uuid4
    with pytest.raises((IndexError, ValueError)):
        fetch_replay_frame(execution_id=str(uuid4()), frame_index=99999)


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_fetch_replay_frame_has_narration():
    """ReplayFrame returned by fetch must include narration text."""
    from vm107.tools.replay.fetch_replay_frame import fetch_replay_frame
    from uuid import uuid4
    frame = fetch_replay_frame(execution_id=str(uuid4()), frame_index=0)
    assert frame.narration is not None
