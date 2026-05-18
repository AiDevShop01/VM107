"""Phase 48 Plan 48-03 Task 3.2 — mid-loop registry mutation cannot reach the loop.

Implements REQ-48-D15 (the "one coherent cognition universe" lock).

CONTEXT § Decision 15: "Mid-loop registry changes are IGNORED. The loop ignores
them — deliberate epistemic stability."

Scenario: monkeypatch ``CapabilityRegistry.get().snapshot_hash`` to a new value
mid-loop. All artifacts inserted for that loop must continue to carry the
ORIGINAL frozen hash, not the mutated value.
"""
from __future__ import annotations

import pytest


def test_mid_loop_registry_mutation_does_not_leak_into_iteration_artifacts(
    mongo_test_db, valid_hypothesis_id, monkeypatch
):
    from core.agents.refinement_orchestrator import (
        persistence,
        snapshot_freeze,
        state as state_mod,
    )

    # 1. Pin registry at v1 and start the loop.
    class _FakeRegV1:
        snapshot_hash = "frozen-v1-aaaa"

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV1())
    )
    monkeypatch.setattr(
        snapshot_freeze.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV1())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-mid-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-mid-1",
    )

    # 2. Now mutate the registry property side-channel.
    class _FakeRegV2:
        snapshot_hash = "mutated-v2-XXXX"

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV2())
    )
    monkeypatch.setattr(
        snapshot_freeze.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegV2())
    )

    # 3. Stamp an artifact through the persistence helper. It must source the
    #    hash from the LOOP STATE doc (frozen v1), NOT from the live registry.
    stamps = persistence.iteration_stamps_for(
        mongo_test_db,
        loop_id="loop-mid-1",
        iteration=0,
        parent_iteration=None,
        refinement_delta_id=None,
        root_hypothesis_id=valid_hypothesis_id,
    )

    # The stamp pack must carry the FROZEN value, not the mutated one.
    assert stamps["registry_snapshot_hash"] == "frozen-v1-aaaa"
    assert stamps["registry_snapshot_hash"] != "mutated-v2-XXXX"


def test_two_iterations_share_same_frozen_hash_after_mutation(
    mongo_test_db, valid_hypothesis_id, monkeypatch
):
    """All artifacts within one loop share registry_snapshot_hash even if the
    registry mutates between iterations."""
    from core.agents.refinement_orchestrator import persistence, state as state_mod

    class _FakeReg:
        snapshot_hash = "iter0-pin"

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-mid-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-mid-2",
    )

    # Iteration 0 stamp
    s0 = persistence.iteration_stamps_for(
        mongo_test_db, loop_id="loop-mid-2", iteration=0,
        parent_iteration=None, refinement_delta_id=None,
        root_hypothesis_id=valid_hypothesis_id,
    )

    # Side-channel: mutate registry between iterations.
    class _FakeRegMutated:
        snapshot_hash = "mutated-between-iterations"

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeRegMutated())
    )

    # Iteration 1 stamp — should match iter 0 (loop frozen).
    s1 = persistence.iteration_stamps_for(
        mongo_test_db, loop_id="loop-mid-2", iteration=1,
        parent_iteration=0, refinement_delta_id="delta-1",
        root_hypothesis_id=valid_hypothesis_id,
    )

    assert s0["registry_snapshot_hash"] == s1["registry_snapshot_hash"] == "iter0-pin"
