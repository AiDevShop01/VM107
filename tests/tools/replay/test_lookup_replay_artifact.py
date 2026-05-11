"""Tests for VM107 lookup_replay_artifact tool — CONTEXT §18.

Returns ReplayArtifactMeta (lightweight) for a given execution_id.
Graduates in 59-07.
"""
import pytest


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_lookup_replay_artifact_returns_meta():
    """lookup_replay_artifact returns ReplayArtifactMeta with execution_id."""
    from vm107.tools.replay.lookup_replay_artifact import lookup_replay_artifact
    from uuid import uuid4
    exec_id = str(uuid4())
    meta = lookup_replay_artifact(execution_id=exec_id, replay_version=None)
    assert meta.execution_id is not None


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_lookup_replay_artifact_latest_version():
    """lookup_replay_artifact with replay_version=None returns the latest version."""
    from vm107.tools.replay.lookup_replay_artifact import lookup_replay_artifact
    from uuid import uuid4
    meta = lookup_replay_artifact(execution_id=str(uuid4()), replay_version=None)
    assert meta.replay_version >= 1


@pytest.mark.xfail(strict=True, reason="Phase 59 — VM107 tool lands in 59-07")
def test_lookup_replay_artifact_specific_version():
    """lookup_replay_artifact with specific replay_version returns that version."""
    from vm107.tools.replay.lookup_replay_artifact import lookup_replay_artifact
    from uuid import uuid4
    meta = lookup_replay_artifact(execution_id=str(uuid4()), replay_version=1)
    assert meta.replay_version == 1
