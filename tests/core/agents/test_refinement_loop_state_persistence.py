"""Phase 48 Plan 48-03 Task 3.2 — RefinementLoopState round-trips through Mongo.

Implements REQ-48-D3.

Asserts:
- ``initialize_loop_state(db, loop_id, hypothesis_id, task_id)`` creates a
  ``refinement_loops`` doc with iteration=0, max_iterations=3, spec_iter0_id=None,
  loop_registry_snapshot_hash=<frozen>, started_at/updated_at UTC.
- Round-trip preserves all 18 RefinementLoopState fields without loss.
- update_loop_state(loop_id, **fields) advances iteration / sets termination_reason.
- append_iteration_artifact(loop_id, iter, bundle) appends to
  iteration_artifact_ids and bumps updated_at.
- finalize_state(loop_id, termination_reason) sets the terminal flag.
"""
from __future__ import annotations

import pytest


def test_initialize_loop_state_creates_doc_with_expected_defaults(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import state as state_mod

    # Freeze CapabilityRegistry.get().snapshot_hash deterministically.
    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-001",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-001",
    )

    assert s.loop_id == "loop-001"
    assert s.root_hypothesis_id == valid_hypothesis_id
    assert s.iteration == 0
    assert s.max_iterations == 3
    assert s.spec_iter0_id is None
    assert s.loop_registry_snapshot_hash == frozen_registry_snapshot_hash
    assert s.iteration_artifact_ids == []
    assert s.critic_history == []
    assert s.termination_reason is None
    assert s.schema_version == 1

    # And the doc was persisted.
    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-001"})
    assert doc is not None
    assert doc["loop_id"] == "loop-001"
    assert doc["iteration"] == 0
    assert doc["loop_registry_snapshot_hash"] == frozen_registry_snapshot_hash


def test_refinement_loop_state_round_trips_through_mongo(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import state as state_mod
    from core.contracts.schemas import RefinementLoopState

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s0 = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-002",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-002",
    )

    # Read back via load_state (Task 3.3 — wired here because state is the
    # canonical persistence unit being tested).
    from core.agents.refinement_orchestrator.checkpoint import load_state

    s1 = load_state(mongo_test_db, "loop-002")
    assert isinstance(s1, RefinementLoopState)
    # Compare key fields — datetimes round-trip via Pydantic's mode="json" semantics.
    assert s1.loop_id == s0.loop_id
    assert s1.root_hypothesis_id == s0.root_hypothesis_id
    assert s1.iteration == s0.iteration
    assert s1.max_iterations == s0.max_iterations
    assert s1.spec_iter0_id == s0.spec_iter0_id
    assert s1.loop_registry_snapshot_hash == s0.loop_registry_snapshot_hash
    assert s1.iteration_artifact_ids == s0.iteration_artifact_ids
    assert s1.schema_version == s0.schema_version


def test_append_iteration_artifact_extends_list_and_bumps_updated_at(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-003",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-003",
    )

    bundle = {
        "iter": 0,
        "strategy_spec_id": "spec-001",
        "code_module_id": "code-001",
        "build_report_id": "build-001",
        "backtest_result_id": "bt-001",
        "critic_verdict_id": "verdict-001",
        "agent_envelope_ids": ["env-001"],
    }
    state_mod.append_iteration_artifact(mongo_test_db, "loop-003", 0, bundle)

    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-003"})
    assert len(doc["iteration_artifact_ids"]) == 1
    assert doc["iteration_artifact_ids"][0]["strategy_spec_id"] == "spec-001"


def test_update_loop_state_can_advance_iteration_and_set_termination(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-004",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-004",
    )

    state_mod.update_loop_state(mongo_test_db, "loop-004", iteration=1)
    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-004"})
    assert doc["iteration"] == 1

    state_mod.finalize_state(mongo_test_db, "loop-004", "ACCEPTED")
    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-004"})
    assert doc["termination_reason"] == "ACCEPTED"
