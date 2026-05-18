"""Phase 48 RefinementLoopState lifecycle helpers.

Implements REQ-48-D3 (state schema) + REQ-48-D15 (frozen registry snapshot at
iteration 0).

Public functions:
    initialize_loop_state(db, *, loop_id, hypothesis_id, task_id) -> RefinementLoopState
    update_loop_state(db, loop_id, **fields) -> None
    append_iteration_artifact(db, loop_id, iteration, bundle) -> None
    finalize_state(db, loop_id, termination_reason) -> None

Implementation notes:
- Mongo collection: ``refinement_loops`` (Plan 48-02 migration 014 created it).
- ``_id == loop_id`` per Phase 43.2 convention.
- ``loop_registry_snapshot_hash`` is captured ONCE at initialize_loop_state via
  ``CapabilityRegistry.get().snapshot_hash`` (PROPERTY access — CONTEXT
  § Decision 15 named it ``current_snapshot_hash()`` which does NOT exist).
- ``spec_iter0_id`` starts None; Plan 08b's main_loop fills it after iteration 0.
- ``schema_version: int = 1``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.contracts.schemas import RefinementLoopState
from core.registry.capability_registry import CapabilityRegistry

_REFINEMENT_LOOPS = "refinement_loops"


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def initialize_loop_state(
    db: Any,
    *,
    loop_id: str,
    hypothesis_id: str,
    task_id: str,
    strategy_family: str = "BREAKOUT",
    strategy_version: str = "0.0.0",
    code_version: str = "0.0.0",
    max_iterations: int = 3,
) -> RefinementLoopState:
    """Create a new RefinementLoopState doc with iteration=0 and a frozen hash.

    The snapshot hash is read ONCE here (property access on the live
    CapabilityRegistry). Subsequent calls to ``freeze_snapshot_hash`` for the
    same loop_id are idempotent and return this same value (CONTEXT §
    Decision 15).
    """
    frozen_hash = CapabilityRegistry.get().snapshot_hash
    now = _utc_now()

    state = RefinementLoopState(
        loop_id=loop_id,
        root_hypothesis_id=hypothesis_id,
        strategy_family=strategy_family,
        loop_registry_snapshot_hash=frozen_hash,
        iteration=0,
        max_iterations=max_iterations,
        iteration_artifact_ids=[],
        strategy_version=strategy_version,
        code_version=code_version,
        critic_history=[],
        veto_history=[],
        identity_scores=[],
        refinement_delta_history=[],
        budget_snapshot={},
        termination_reason=None,
        started_at=now,
        updated_at=now,
        spec_iter0_id=None,
        schema_version=1,
    )

    doc = state.model_dump(mode="json")
    doc["_id"] = loop_id
    # Stash the task_id alongside (unique-sparse index per Plan 02 migration 014).
    doc["task_id"] = task_id

    db[_REFINEMENT_LOOPS].insert_one(doc)
    return state


def update_loop_state(db: Any, loop_id: str, **fields: Any) -> None:
    """Apply a $set update with auto-bumped ``updated_at``.

    Plan 48-04 + 48-05 use this to advance ``iteration`` and to record
    per-iteration budget snapshots, identity scores, and refinement delta ids.
    """
    if not fields:
        return None
    fields["updated_at"] = _utc_now().isoformat()
    db[_REFINEMENT_LOOPS].update_one({"_id": loop_id}, {"$set": fields})
    return None


def append_iteration_artifact(
    db: Any, loop_id: str, iteration: int, bundle: dict[str, Any]
) -> None:
    """Append an iteration-artifact-id bundle to RefinementLoopState.iteration_artifact_ids.

    Bundle shape per CONTEXT § Decision 3:
        {iter, strategy_spec_id, code_module_id, build_report_id,
         backtest_result_id, critic_verdict_id, agent_envelope_ids[]}
    """
    entry = dict(bundle)
    entry.setdefault("iter", iteration)
    db[_REFINEMENT_LOOPS].update_one(
        {"_id": loop_id},
        {
            "$push": {"iteration_artifact_ids": entry},
            "$set": {"updated_at": _utc_now().isoformat()},
        },
    )
    return None


def finalize_state(db: Any, loop_id: str, termination_reason: str) -> None:
    """Set termination_reason + bump updated_at. CONTEXT § Decision 4 enum value."""
    db[_REFINEMENT_LOOPS].update_one(
        {"_id": loop_id},
        {
            "$set": {
                "termination_reason": termination_reason,
                "updated_at": _utc_now().isoformat(),
            }
        },
    )
    return None
