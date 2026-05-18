"""Phase 48 Plan 48-03 Task 3.3 — terminations preserve the full iteration trajectory.

Implements REQ-48-D13 (CONTEXT § Decision 13 — append-only WORM, refinement
archaeology > storage cost).

Scenario: simulate a loop with 3 iterations of stamped artifacts.  Finalize
with a terminal reason (HARD_VETO / IDENTITY_DRIFT / BUILD_FAILURE — any of
the non-ACCEPTED termination_reasons). Assert that iterations 0..N-1 artifacts
are still queryable in their respective collections.
"""
from __future__ import annotations

import pytest


def test_termination_does_not_discard_prior_iteration_artifacts(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import (
        persistence,
        state as state_mod,
    )

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-traj-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-traj-1",
    )

    # Pretend emit_event always succeeds (Plan 48-03 substrate; HTTP is mocked).
    monkeypatch.setattr(persistence, "emit_event", lambda *a, **kw: None)

    # Persist three iterations worth of strategy_specs + critic_verdicts.
    for i in range(3):
        for collection, prefix in (("strategy_specs", "spec"), ("critic_verdicts", "verdict")):
            stamped = persistence._stamp_artifact(
                mongo_test_db,
                artifact={"_id": f"{prefix}-iter{i}"},
                loop_id="loop-traj-1",
                iteration=i,
                parent_iteration=i - 1 if i > 0 else None,
                refinement_delta_id=f"delta-{i}" if i > 0 else None,
                root_hypothesis_id=valid_hypothesis_id,
            )
            persistence.persist_atomically(
                mongo_test_db,
                state=s,
                artifact_dict=stamped,
                collection_name=collection,
                event_type="iteration_started",
                event_payload={"loop_id": "loop-traj-1", "iteration_number": i},
            )

    # Now simulate termination at iteration 2 — HARD_VETO.
    state_mod.finalize_state(mongo_test_db, "loop-traj-1", "HARD_VETO")

    # ASSERT: iterations 0 + 1 artifacts are STILL queryable.
    for collection, prefix in (("strategy_specs", "spec"), ("critic_verdicts", "verdict")):
        docs = list(
            mongo_test_db[collection].find({"refinement_loop_id": "loop-traj-1"})
        )
        assert len(docs) == 3, (
            f"trajectory preservation violated: {collection} has {len(docs)} docs, expected 3"
        )
        ids = sorted(d["_id"] for d in docs)
        assert ids == [f"{prefix}-iter0", f"{prefix}-iter1", f"{prefix}-iter2"]


def test_termination_persists_termination_reason_without_purging_state(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """RefinementLoopState retains iteration_artifact_ids even after termination."""
    from core.agents.refinement_orchestrator import state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-traj-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-traj-2",
    )

    for i in range(2):
        state_mod.append_iteration_artifact(
            mongo_test_db,
            "loop-traj-2",
            i,
            {"strategy_spec_id": f"spec-{i}", "critic_verdict_id": f"verdict-{i}"},
        )

    state_mod.finalize_state(mongo_test_db, "loop-traj-2", "IDENTITY_DRIFT")

    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-traj-2"})
    assert doc["termination_reason"] == "IDENTITY_DRIFT"
    assert len(doc["iteration_artifact_ids"]) == 2, (
        "termination must NOT prune iteration_artifact_ids"
    )
