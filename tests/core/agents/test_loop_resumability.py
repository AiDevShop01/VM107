"""Phase 48 Plan 48-03 Task 3.3 — orchestrator can resume from Mongo state.

Implements REQ-48-D17 (CONTEXT § Decision 17 — resumable task state).

Scenario: build a state, drop the in-memory orchestrator reference, instantiate
a fresh resume_or_initialize() call with the same loop_id — state must come
back intact with the same iteration counter, no re-initialization, no second
registry-snapshot freeze.
"""
from __future__ import annotations

import pytest


def test_resume_or_initialize_returns_existing_state(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import (
        checkpoint,
        state as state_mod,
    )

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s0 = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-resume-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-resume-1",
    )

    # Advance iteration so resumption is observable.
    state_mod.update_loop_state(mongo_test_db, "loop-resume-1", iteration=2)

    # Simulate orchestrator restart: drop in-memory state. Now another
    # instance calls resume_or_initialize with the SAME loop_id.
    del s0

    # Even if the registry mutates between "runs", resume must not re-freeze.
    class _FakeRegMutated:
        snapshot_hash = "mutated-after-restart"

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegMutated())
    )

    resumed = checkpoint.resume_or_initialize(
        mongo_test_db,
        loop_id="loop-resume-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-resume-1",
    )

    assert resumed.loop_id == "loop-resume-1"
    assert resumed.iteration == 2, "resumed state must carry the recorded iteration"
    assert resumed.loop_registry_snapshot_hash == frozen_registry_snapshot_hash, (
        "resume must NOT re-freeze; the original hash survives"
    )


def test_resume_or_initialize_creates_state_when_absent(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import (
        checkpoint,
        state as state_mod,
    )

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s = checkpoint.resume_or_initialize(
        mongo_test_db,
        loop_id="loop-resume-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-resume-2",
    )

    assert s.loop_id == "loop-resume-2"
    assert s.iteration == 0
    assert s.loop_registry_snapshot_hash == frozen_registry_snapshot_hash


def test_resume_returns_terminal_state_unchanged(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """Once a loop has terminated, resume returns the terminal state — the
    caller (Plan 48-04) decides whether to start a fresh loop.
    """
    from core.agents.refinement_orchestrator import (
        checkpoint,
        state as state_mod,
    )

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-resume-3",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-resume-3",
    )
    state_mod.finalize_state(mongo_test_db, "loop-resume-3", "MAX_ITERATIONS")

    resumed = checkpoint.resume_or_initialize(
        mongo_test_db,
        loop_id="loop-resume-3",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-resume-3",
    )
    assert resumed.termination_reason == "MAX_ITERATIONS"
    assert checkpoint.is_terminal(resumed) is True
