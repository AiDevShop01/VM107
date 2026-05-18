"""Phase 48 Pattern 51 atomic-persistence helpers.

Implements REQ-48-D13 + REQ-48-D17.

CONTEXT § Decision 13: every iteration artifact carries 6 stamp fields
(iteration_number, parent_iteration, refinement_delta_id,
registry_snapshot_hash, root_hypothesis_id, refinement_loop_id).

CONTEXT § Decision 18 + Pattern 51: refinement events emitted IMMEDIATELY in
the same atomic block as artifact persistence. On emit failure, the orchestrator
catches and terminates with BUILD_FAILURE (logged + raised here; the caller
decides whether to roll back). Mongo lacks first-class cross-collection
transactions in single-replica deployments, so this module implements a
"write-then-emit" sequence with explicit rollback semantics on emit failure.

Public functions:
    iteration_stamps_for(db, loop_id, iteration, parent_iteration,
                        refinement_delta_id, root_hypothesis_id) -> dict
    _stamp_artifact(db, *, artifact, ...) -> dict
    persist_atomically(db, *, state, artifact_dict, collection_name,
                       event_type, event_payload) -> None
"""
from __future__ import annotations

import logging
from typing import Any

from core.contracts.schemas import RefinementLoopState
from core.events.phase56_client import Phase56EmitError, emit_event

log = logging.getLogger("vm107.refinement_orchestrator.persistence")


_REFINEMENT_LOOPS = "refinement_loops"

_REQUIRED_STAMP_FIELDS = (
    "iteration_number",
    "parent_iteration",
    "refinement_delta_id",
    "registry_snapshot_hash",
    "root_hypothesis_id",
    "refinement_loop_id",
)


def iteration_stamps_for(
    db: Any,
    *,
    loop_id: str,
    iteration: int,
    parent_iteration: int | None,
    refinement_delta_id: str | None,
    root_hypothesis_id: str,
) -> dict[str, Any]:
    """Build the 6-field stamp pack for a single iteration artifact.

    Reads ``loop_registry_snapshot_hash`` from the LOOP STATE doc (NOT the
    live registry) — that field was frozen at iteration 0 and never changes.
    Per CONTEXT § Decision 15: "mid-loop registry changes are IGNORED."
    """
    state_doc = db[_REFINEMENT_LOOPS].find_one(
        {"_id": loop_id}, {"loop_registry_snapshot_hash": 1}
    )
    if not state_doc or "loop_registry_snapshot_hash" not in state_doc:
        raise ValueError(
            f"refinement_loops[{loop_id}].loop_registry_snapshot_hash is not set; "
            "call initialize_loop_state before stamping iteration artifacts"
        )

    return {
        "iteration_number": iteration,
        "parent_iteration": parent_iteration,
        "refinement_delta_id": refinement_delta_id,
        "registry_snapshot_hash": state_doc["loop_registry_snapshot_hash"],
        "root_hypothesis_id": root_hypothesis_id,
        "refinement_loop_id": loop_id,
    }


def _stamp_artifact(
    db: Any,
    *,
    artifact: dict[str, Any],
    loop_id: str,
    iteration: int,
    parent_iteration: int | None,
    refinement_delta_id: str | None,
    root_hypothesis_id: str,
) -> dict[str, Any]:
    """Attach the 6 stamp fields to an artifact dict. Returns the stamped dict."""
    stamps = iteration_stamps_for(
        db,
        loop_id=loop_id,
        iteration=iteration,
        parent_iteration=parent_iteration,
        refinement_delta_id=refinement_delta_id,
        root_hypothesis_id=root_hypothesis_id,
    )
    stamped = dict(artifact)
    stamped.update(stamps)
    return stamped


def _verify_stamps(artifact_dict: dict[str, Any]) -> None:
    """Raise ValueError if any of the 6 required stamps are missing."""
    missing = [f for f in _REQUIRED_STAMP_FIELDS if f not in artifact_dict]
    if missing:
        raise ValueError(
            "iteration artifact is missing required stamp field(s): "
            + ", ".join(missing)
        )


def persist_atomically(
    db: Any,
    *,
    state: RefinementLoopState,
    artifact_dict: dict[str, Any],
    collection_name: str,
    event_type: str,
    event_payload: dict[str, Any],
    correlation_id: str | None = None,
    causality_scope: str = "IDEA",
) -> None:
    """Pattern 51: write artifact + emit Phase 56 event in one logical block.

    Sequence:
        1. Verify all 6 stamp fields are present on ``artifact_dict``.
        2. Insert into ``db[collection_name]``.
        3. Append the artifact_id bundle entry to RefinementLoopState
           (one row per iteration, additive).
        4. Emit the Phase 56 event via ``emit_event``.
        5. On emit failure: log + raise Phase56EmitError. The caller (orchestrator
           in Plan 48-04+) catches and terminates with BUILD_FAILURE.

    Rollback semantics: Mongo lacks single-node cross-collection ACID for
    arbitrary documents; this module performs a best-effort rollback by
    deleting the inserted artifact doc on emit failure. The loop's
    RefinementLoopState update is left in place (it's append-only and the
    orchestrator's next persist call will treat the half-finished iteration
    as a no-op or retry).

    Raises:
        ValueError: any of the 6 stamps is missing on ``artifact_dict``.
        Phase56EmitError: emit_event failed (and artifact was deleted).
    """
    _verify_stamps(artifact_dict)

    correlation_id = correlation_id or state.loop_id

    # Step 1: insert artifact.
    inserted_id: Any = None
    try:
        result = db[collection_name].insert_one(artifact_dict)
        inserted_id = getattr(result, "inserted_id", artifact_dict.get("_id"))
    except Exception:
        log.exception(
            "persistence: failed to insert artifact into %s (loop=%s iter=%s)",
            collection_name, state.loop_id, artifact_dict.get("iteration_number"),
        )
        raise

    # Step 2: emit Phase 56 event.
    try:
        emit_event(
            event_type=event_type,
            category="cognition",
            correlation_id=correlation_id,
            payload=event_payload,
            causality_scope=causality_scope,
        )
    except Phase56EmitError:
        # Best-effort rollback of the artifact insert so the storage layer
        # stays consistent with the event stream.
        log.error(
            "persistence: emit_event failed after artifact insert; "
            "rolling back artifact_id=%s in %s",
            inserted_id, collection_name,
        )
        try:
            db[collection_name].delete_one({"_id": inserted_id})
        except Exception:
            log.exception(
                "persistence: rollback delete also failed (loop=%s artifact=%s)",
                state.loop_id, inserted_id,
            )
        raise
    return None
