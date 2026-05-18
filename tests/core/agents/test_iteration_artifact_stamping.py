"""Phase 48 Plan 48-03 Task 3.2 — every iteration artifact carries all 6 stamps.

Implements REQ-48-D13.

CONTEXT § Decision 13: every iteration artifact includes
``iteration_number``, ``parent_iteration``, ``refinement_delta_id``,
``registry_snapshot_hash``, ``root_hypothesis_id``, ``refinement_loop_id``.

``persistence._stamp_artifact`` enforces this contract — missing any stamp
field raises ValueError BEFORE Mongo insert.
"""
from __future__ import annotations

import pytest


_REQUIRED_STAMPS = {
    "iteration_number",
    "parent_iteration",
    "refinement_delta_id",
    "registry_snapshot_hash",
    "root_hypothesis_id",
    "refinement_loop_id",
}


def test_stamp_artifact_attaches_all_six_fields(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import persistence, state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-stamp-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-stamp-1",
    )

    raw = {"_id": "spec-1", "fields": {"strategy_family": "BREAKOUT"}}
    stamped = persistence._stamp_artifact(
        mongo_test_db,
        artifact=raw,
        loop_id="loop-stamp-1",
        iteration=2,
        parent_iteration=1,
        refinement_delta_id="delta-x",
        root_hypothesis_id=valid_hypothesis_id,
    )

    for key in _REQUIRED_STAMPS:
        assert key in stamped, f"missing stamp: {key}"
    assert stamped["iteration_number"] == 2
    assert stamped["parent_iteration"] == 1
    assert stamped["refinement_delta_id"] == "delta-x"
    assert stamped["registry_snapshot_hash"] == frozen_registry_snapshot_hash
    assert stamped["root_hypothesis_id"] == valid_hypothesis_id
    assert stamped["refinement_loop_id"] == "loop-stamp-1"


def test_persist_atomically_rejects_artifact_missing_required_stamp(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """If a caller bypasses _stamp_artifact and hands a raw doc to
    persist_atomically, the helper must reject it.
    """
    from core.agents.refinement_orchestrator import persistence, state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-stamp-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-stamp-2",
    )

    # Build an artifact that's missing `root_hypothesis_id`.
    bad_doc = {
        "_id": "spec-broken",
        "iteration_number": 0,
        "parent_iteration": None,
        "refinement_delta_id": None,
        "registry_snapshot_hash": frozen_registry_snapshot_hash,
        "refinement_loop_id": "loop-stamp-2",
        # missing root_hypothesis_id
    }

    # No-op emit so the test doesn't try to POST.
    def _fake_emit(*a, **kw):
        return None

    monkeypatch.setattr(persistence, "emit_event", _fake_emit)

    with pytest.raises(ValueError, match="root_hypothesis_id"):
        persistence.persist_atomically(
            mongo_test_db,
            state=s,
            artifact_dict=bad_doc,
            collection_name="strategy_specs",
            event_type="iteration_started",
            event_payload={"loop_id": "loop-stamp-2"},
        )


def test_persist_atomically_inserts_artifact_and_calls_emit_event(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """Happy path — well-stamped doc lands in the collection and emit_event fires."""
    from core.agents.refinement_orchestrator import persistence, state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    s = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-stamp-3",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-stamp-3",
    )

    raw = {"_id": "spec-good", "fields": {"strategy_family": "BREAKOUT"}}
    stamped = persistence._stamp_artifact(
        mongo_test_db,
        artifact=raw,
        loop_id="loop-stamp-3",
        iteration=0,
        parent_iteration=None,
        refinement_delta_id=None,
        root_hypothesis_id=valid_hypothesis_id,
    )

    emit_calls = []

    def _spy_emit(event_type, category, correlation_id, payload, **kw):
        emit_calls.append({
            "event_type": event_type,
            "category": category,
            "correlation_id": correlation_id,
            "payload": payload,
        })
        return None

    monkeypatch.setattr(persistence, "emit_event", _spy_emit)

    persistence.persist_atomically(
        mongo_test_db,
        state=s,
        artifact_dict=stamped,
        collection_name="strategy_specs",
        event_type="iteration_started",
        event_payload={"loop_id": "loop-stamp-3", "iteration_number": 0},
    )

    doc = mongo_test_db["strategy_specs"].find_one({"_id": "spec-good"})
    assert doc is not None
    assert doc["refinement_loop_id"] == "loop-stamp-3"
    assert len(emit_calls) == 1
    assert emit_calls[0]["event_type"] == "iteration_started"
