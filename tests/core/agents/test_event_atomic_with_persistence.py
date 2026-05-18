"""Phase 48 Plan 07 — Pattern 51 atomic-with-persistence test.

CONTEXT § Decision 18 + Pattern 51: refinement events emitted IMMEDIATELY
in the same atomic block as artifact persistence. ``persist_atomically``
(Plan 03) executes the sequence:

  1. Insert artifact into the target Mongo collection.
  2. Emit the Phase 56 event via core.events.phase56_client.emit_event.
  3. On emit failure: delete the just-inserted artifact (bounded rollback).

This test verifies the ORDERING of those two side effects so the
Phase 56 store never contains an event whose artifact was never written,
and the artifact collection never contains a doc whose event never fired.

REQ-48-D17 (Pattern 51 atomic emission).
REQ-48-D18 (orchestrator sole emitter).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


@pytest.fixture
def loop_state(frozen_registry_snapshot_hash):
    """Minimal RefinementLoopState seeded into mongomock."""
    from core.contracts.schemas import RefinementLoopState

    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop-phase48-07-atomic",
        root_hypothesis_id="hyp-test",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash=frozen_registry_snapshot_hash,
        iteration=0,
        strategy_version="0.1.0",
        code_version="0.1.0",
        started_at=now,
        updated_at=now,
    )


@pytest.fixture
def seeded_db(mongo_test_db, loop_state, frozen_registry_snapshot_hash):
    """Insert the loop_state into refinement_loops so iteration_stamps_for resolves."""
    mongo_test_db["refinement_loops"].insert_one(
        {
            "_id": loop_state.loop_id,
            "loop_registry_snapshot_hash": frozen_registry_snapshot_hash,
        }
    )
    return mongo_test_db


def _build_stamped_artifact(loop_id: str, snapshot_hash: str) -> dict:
    """Build a valid 6-field-stamped artifact dict for persist_atomically."""
    return {
        "_id": "artifact-001",
        "iteration_number": 0,
        "parent_iteration": None,
        "refinement_delta_id": None,
        "registry_snapshot_hash": snapshot_hash,
        "root_hypothesis_id": "hyp-test",
        "refinement_loop_id": loop_id,
        "body": "test artifact body",
    }


def test_persist_atomically_writes_artifact_then_emits_event(
    monkeypatch, seeded_db, loop_state, frozen_registry_snapshot_hash
):
    """Mongo insert MUST precede emit_event in the same atomic block.

    Track call ordering via a list shared by both monkeypatched targets.
    """
    from core.agents.refinement_orchestrator import persistence as pa
    from core.events.refinement_events import emit_iteration_started  # noqa: F401

    call_log: list[str] = []

    # Wrap Mongo insert: append "mongo_insert" to call_log when called.
    real_collection = seeded_db["test_iteration_artifacts"]
    original_insert = real_collection.insert_one

    def tracked_insert(doc):
        call_log.append("mongo_insert")
        return original_insert(doc)

    monkeypatch.setattr(real_collection, "insert_one", tracked_insert)

    # Patch emit_event in persistence module so we capture ordering, not at
    # the helper level — the orchestrator's persist_atomically imports
    # emit_event directly.
    def tracked_emit(
        event_type, category, correlation_id, payload, *, causality_scope="IDEA"
    ):
        call_log.append("emit_event")
        return None

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.persistence.emit_event",
        tracked_emit,
    )

    artifact = _build_stamped_artifact(loop_state.loop_id, frozen_registry_snapshot_hash)

    pa.persist_atomically(
        seeded_db,
        state=loop_state,
        artifact_dict=artifact,
        collection_name="test_iteration_artifacts",
        event_type="iteration_started",
        event_payload={
            "loop_id": loop_state.loop_id,
            "iteration_number": 0,
            "root_hypothesis_id": "hyp-test",
            "registry_snapshot_hash": frozen_registry_snapshot_hash,
        },
    )

    # Strict ordering: mongo_insert BEFORE emit_event, both called exactly once.
    assert call_log == ["mongo_insert", "emit_event"], (
        f"Pattern 51 ordering violated: expected ['mongo_insert', 'emit_event'], "
        f"got {call_log}"
    )

    # Artifact is in the collection.
    persisted = seeded_db["test_iteration_artifacts"].find_one({"_id": artifact["_id"]})
    assert persisted is not None, "Artifact missing after persist_atomically"


def test_persist_atomically_rolls_back_artifact_on_emit_failure(
    monkeypatch, seeded_db, loop_state, frozen_registry_snapshot_hash
):
    """Emit failure → artifact rolled back; no orphan doc in collection.

    Pattern 51 guarantee: storage layer and event stream stay consistent.
    """
    from core.agents.refinement_orchestrator import persistence as pa
    from core.events.phase56_client import Phase56EmitError

    def failing_emit(*args, **kwargs):
        raise Phase56EmitError(
            "simulated emit failure", status_code=503, body="bad gateway"
        )

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.persistence.emit_event",
        failing_emit,
    )

    artifact = _build_stamped_artifact(loop_state.loop_id, frozen_registry_snapshot_hash)

    with pytest.raises(Phase56EmitError):
        pa.persist_atomically(
            seeded_db,
            state=loop_state,
            artifact_dict=artifact,
            collection_name="test_iteration_artifacts",
            event_type="iteration_started",
            event_payload={
                "loop_id": loop_state.loop_id,
                "iteration_number": 0,
                "root_hypothesis_id": "hyp-test",
                "registry_snapshot_hash": frozen_registry_snapshot_hash,
            },
        )

    # The artifact MUST have been rolled back.
    persisted = seeded_db["test_iteration_artifacts"].find_one({"_id": artifact["_id"]})
    assert persisted is None, (
        "Pattern 51 rollback violated: artifact still present after emit failure"
    )


def test_persist_atomically_no_emit_when_insert_fails(
    monkeypatch, seeded_db, loop_state, frozen_registry_snapshot_hash
):
    """Insert failure → emit_event is NEVER called (no orphan event).

    Storage layer / event stream consistency: an artifact that never wrote
    must NEVER produce an event in the Phase 56 store.
    """
    from core.agents.refinement_orchestrator import persistence as pa

    emit_call_count = {"count": 0}

    def tracked_emit(*args, **kwargs):
        emit_call_count["count"] += 1
        return None

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.persistence.emit_event",
        tracked_emit,
    )

    # Make Mongo insert raise.
    def failing_insert(doc):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(
        seeded_db["test_iteration_artifacts"], "insert_one", failing_insert
    )

    artifact = _build_stamped_artifact(loop_state.loop_id, frozen_registry_snapshot_hash)

    with pytest.raises(RuntimeError):
        pa.persist_atomically(
            seeded_db,
            state=loop_state,
            artifact_dict=artifact,
            collection_name="test_iteration_artifacts",
            event_type="iteration_started",
            event_payload={"loop_id": loop_state.loop_id, "iteration_number": 0,
                           "root_hypothesis_id": "hyp-test",
                           "registry_snapshot_hash": frozen_registry_snapshot_hash},
        )

    assert emit_call_count["count"] == 0, (
        "Pattern 51 violated: emit_event was called even though insert failed"
    )


def test_persist_atomically_validates_stamp_fields_before_insert(
    monkeypatch, seeded_db, loop_state, frozen_registry_snapshot_hash
):
    """An artifact missing stamp fields raises BEFORE insert and BEFORE emit."""
    from core.agents.refinement_orchestrator import persistence as pa

    emit_call_count = {"count": 0}
    insert_call_count = {"count": 0}

    def tracked_emit(*args, **kwargs):
        emit_call_count["count"] += 1
        return None

    def tracked_insert(doc):
        insert_call_count["count"] += 1
        return MagicMock(inserted_id=doc.get("_id"))

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.persistence.emit_event",
        tracked_emit,
    )
    monkeypatch.setattr(
        seeded_db["test_iteration_artifacts"], "insert_one", tracked_insert
    )

    incomplete = {"_id": "x", "iteration_number": 0}  # missing 5 of 6 stamps

    with pytest.raises(ValueError):
        pa.persist_atomically(
            seeded_db,
            state=loop_state,
            artifact_dict=incomplete,
            collection_name="test_iteration_artifacts",
            event_type="iteration_started",
            event_payload={"loop_id": loop_state.loop_id, "iteration_number": 0,
                           "root_hypothesis_id": "hyp-test",
                           "registry_snapshot_hash": frozen_registry_snapshot_hash},
        )

    assert insert_call_count["count"] == 0, "Insert called despite missing stamps"
    assert emit_call_count["count"] == 0, "Emit called despite missing stamps"
