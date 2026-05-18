"""Phase 48 Plan 48-03 Task 3.3 — replay snapshot validation primitive.

Implements REQ-48-D15. CONTEXT § Decision 15: replay APIs MUST require
``registry_snapshot_hash``; mismatch = HARD FAIL, no "best effort replay."

The primitive ``validate_snapshot_for_replay(stored_hash)`` is the surface
that Plan 48-09's ReplayQueryService.get_refinement_timeline will call before
returning any cognition events.
"""
from __future__ import annotations

import pytest


def test_validate_snapshot_for_replay_raises_on_mismatch(monkeypatch):
    from core.events import phase56_client

    class _FakeRegistry:
        snapshot_hash = "live-snapshot-A"

    monkeypatch.setattr(
        phase56_client.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegistry())
    )

    with pytest.raises(phase56_client.SnapshotMismatchError) as ei:
        phase56_client.validate_snapshot_for_replay("stored-snapshot-B")

    err = ei.value
    assert err.stored_hash == "stored-snapshot-B"
    assert err.current_hash == "live-snapshot-A"


def test_validate_snapshot_for_replay_returns_none_on_match(monkeypatch):
    from core.events import phase56_client

    class _FakeRegistry:
        snapshot_hash = "matching-snapshot-Z"

    monkeypatch.setattr(
        phase56_client.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegistry())
    )

    assert phase56_client.validate_snapshot_for_replay("matching-snapshot-Z") is None


def test_snapshot_mismatch_error_inherits_from_runtimeerror():
    """SnapshotMismatchError must be a RuntimeError subclass so callers can
    catch the broad ``RuntimeError`` envelope when needed.
    """
    from core.events.phase56_client import SnapshotMismatchError

    assert issubclass(SnapshotMismatchError, RuntimeError)


def test_validate_snapshot_for_replay_exported_from_package():
    """The primitive must be importable from ``core.events`` (package surface)."""
    from core.events import validate_snapshot_for_replay, SnapshotMismatchError  # noqa: F401
