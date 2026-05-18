"""Phase 48 refinement rejection path.

REQ-48-D12. CONTEXT § Decision 12.

When the refinement orchestrator decides a strategy must be archived
(HARD_VETO, IDENTITY_DRIFT, CONVERGENCE_STALL, BUDGET_EXCEEDED_*,
MAX_ITERATIONS, CRITIC_REJECT, BUILD_FAILURE + 5 sub-states), this module:

  1. Defensively re-checks the loop state row exists in Mongo.
  2. Derives the ``failure_surface_summary`` from the termination_reason.
  3. Builds the 12-field rejected_strategies doc (CONTEXT § Decision 12).
  4. Inserts it into ``rejected_strategies`` Mongo collection with the hidden
     ``_worm_locked: True`` flag stamped on insert (application-layer WORM).
  5. Emits ``strategy_rejected`` Phase 56 event (Pattern 51 atomic-with-persist).

**NO REGISTRY EMIT.** Rejected strategies are NEVER registered as
capabilities — capability surfaces are strictly opt-in via promotion (see
``acceptance_path``). The test_rejection_no_registry_emit AST guard
enforces that this module does not import strategy_yaml_emitter.

Sole-emitter invariant: this module lives under
``core/agents/refinement_orchestrator/`` and is therefore an authorized
caller of ``core.events.refinement_events`` per the Plan 07 AST guard.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from core.contracts.exceptions import OrphanStrategyError
from core.contracts.schemas import CriticVerdict, RefinementLoopState, RefinementTarget
from core.events.refinement_events import emit_strategy_rejected

log = logging.getLogger("vm107.refinement_orchestrator.rejection_path")

_REJECTED_STRATEGIES = "rejected_strategies"
_REFINEMENT_LOOPS = "refinement_loops"
_REJECTED_BY_VERSION = "refinement_orchestrator@1.0.0"

# Termination reasons that map to the BUILD_FAILURE family (top-level bucket +
# 5 sub-states per CONTEXT § Decision 4 / Plan 48-01 planner discretion).
_BUILD_FAILURE_FAMILY = frozenset(
    {
        "BUILD_FAILURE",
        "BUILD_FAILED",
        "CRITIC_DEGRADED",
        "STRATEGY_DEGRADED",
        "CODE_DEGRADED",
        "BACKTEST_DEGRADED",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _assert_loop_state_present(db: Any, *, loop_id: str) -> dict[str, Any]:
    """Reject rejection-path invocations against a missing RefinementLoopState row."""
    doc = db[_REFINEMENT_LOOPS].find_one({"_id": loop_id})
    if not doc:
        raise OrphanStrategyError(
            f"Refinement loop state missing for loop_id={loop_id!r}. "
            "Rejection path requires initialize_loop_state to have been called first."
        )
    return doc


def derive_failure_surface_summary(
    *,
    termination_reason: str,
    verdict_or_none: CriticVerdict | None,
    veto_history: list[dict[str, Any]],
    identity_diff_breakdown: list[dict[str, Any]] | None,
    critic_history: list[str],
    repeated_targets: list[RefinementTarget] | None,
) -> dict[str, Any]:
    """Derive ``failure_surface_summary`` from termination_reason + supporting state.

    Returns:
        ``{"primary_failure_mode": str, "secondary_failure_modes": list[str]}``

    Mapping table (CONTEXT § Decision 12 + planner discretion):
      HARD_VETO              -> primary=catastrophic_metric, sec=veto metric names
      IDENTITY_DRIFT         -> primary=identity_drift,     sec=diff field names
      CONVERGENCE_STALL      -> primary=convergence_stall,  sec=repeated issue_types
      BUDGET_EXCEEDED_ITER   -> primary=budget_exhaustion,  sec=["ITERATION"]
      BUDGET_EXCEEDED_LOOP   -> primary=budget_exhaustion,  sec=["LOOP"]
      MAX_ITERATIONS         -> primary=max_iterations,     sec=critic_history verdicts
      CRITIC_REJECT          -> primary=no_edge,            sec=verdict.failure_modes
      BUILD_FAILURE family   -> primary=pipeline_failure,   sec=[degraded_stage]
      <unknown>              -> primary=<termination_reason>, sec=[]
    """
    tr = termination_reason

    if tr == "HARD_VETO":
        return {
            "primary_failure_mode": "catastrophic_metric",
            "secondary_failure_modes": [v.get("metric", "") for v in veto_history],
        }

    if tr == "IDENTITY_DRIFT":
        diff = identity_diff_breakdown or []
        return {
            "primary_failure_mode": "identity_drift",
            "secondary_failure_modes": [d.get("field", "") for d in diff],
        }

    if tr == "CONVERGENCE_STALL":
        targets = repeated_targets or []
        return {
            "primary_failure_mode": "convergence_stall",
            "secondary_failure_modes": [t.issue_type for t in targets],
        }

    if tr == "BUDGET_EXCEEDED_ITERATION":
        return {
            "primary_failure_mode": "budget_exhaustion",
            "secondary_failure_modes": ["ITERATION"],
        }

    if tr == "BUDGET_EXCEEDED_LOOP":
        return {
            "primary_failure_mode": "budget_exhaustion",
            "secondary_failure_modes": ["LOOP"],
        }

    if tr == "MAX_ITERATIONS":
        return {
            "primary_failure_mode": "max_iterations",
            "secondary_failure_modes": list(critic_history),
        }

    if tr == "CRITIC_REJECT":
        modes = list(verdict_or_none.failure_modes) if verdict_or_none else []
        return {
            "primary_failure_mode": "no_edge",
            "secondary_failure_modes": modes,
        }

    if tr in _BUILD_FAILURE_FAMILY:
        return {
            "primary_failure_mode": "pipeline_failure",
            "secondary_failure_modes": [tr],
        }

    # Safe default for any future termination_reason we don't yet know about.
    return {
        "primary_failure_mode": tr,
        "secondary_failure_modes": [],
    }


def _build_rejected_doc(
    *,
    rejected_strategy_id: str,
    state: RefinementLoopState,
    termination_reason: str,
    verdict_or_none: CriticVerdict | None,
    final_iteration: int,
    iteration_artifact_ids: list[dict[str, Any]],
    failure_surface_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build the 12-field rejected_strategies doc per CONTEXT § Decision 12."""
    return {
        "_id": rejected_strategy_id,
        "rejected_strategy_id": rejected_strategy_id,
        "root_hypothesis_id": state.root_hypothesis_id,
        "strategy_family": state.strategy_family,
        "refinement_loop_id": state.loop_id,
        "termination_reason": termination_reason,
        "iteration_count": final_iteration,
        "final_identity_score": (
            state.identity_scores[-1] if state.identity_scores else None
        ),
        "final_critic_verdict_id": (
            verdict_or_none.source_critic_verdict_id if verdict_or_none else None
        ),
        "veto_history": list(state.veto_history),
        "refinement_history": list(state.refinement_delta_history),
        "iteration_artifact_ids": list(iteration_artifact_ids),
        "registry_snapshot_hash": state.loop_registry_snapshot_hash,
        "rejected_at": _utc_now_iso(),
        "rejected_by": _REJECTED_BY_VERSION,
        "failure_surface_summary": failure_surface_summary,
        "schema_version": 1,
        # Application-layer WORM flag (Decision 12 — append-only).
        "_worm_locked": True,
    }


def reject_strategy(
    db: Any,
    *,
    state: RefinementLoopState,
    termination_reason: str,
    verdict_or_none: CriticVerdict | None,
    final_iteration: int,
    iteration_artifact_ids: list[dict[str, Any]],
    identity_diff_breakdown: list[dict[str, Any]] | None = None,
    repeated_targets: list[RefinementTarget] | None = None,
) -> str:
    """Archive a refinement loop to rejected_strategies + emit Phase 56 event.

    Pattern 51 ordering (CONTEXT § Decision 18 + Plan 07):
      1. Defensive orphan check on RefinementLoopState row.
      2. Insert rejected_strategies doc (Mongo).
      3. Emit strategy_rejected Phase 56 event.

    NO registry YAML emission (Decision 12 — rejected ≠ capability).

    Args:
        db: pymongo / mongomock Database handle.
        state: RefinementLoopState carrying loop metadata.
        termination_reason: one of TerminationReason's 14 enum values.
        verdict_or_none: CriticVerdict if the rejection traces to a Critic
            decision; ``None`` when terminated by deterministic gate
            (HARD_VETO / IDENTITY_DRIFT / BUDGET_EXCEEDED_*).
        final_iteration: int iteration at which termination fired.
        iteration_artifact_ids: full trajectory bundle list.
        identity_diff_breakdown: only meaningful when termination_reason ==
            ``IDENTITY_DRIFT``. Otherwise None.
        repeated_targets: only meaningful when termination_reason ==
            ``CONVERGENCE_STALL``. Otherwise None.

    Returns:
        rejected_strategy_id (uuid4 string).

    Raises:
        OrphanStrategyError: RefinementLoopState row missing for state.loop_id.
        Phase56EmitError: event emit failed.
    """
    # Defensive orphan check.
    _assert_loop_state_present(db, loop_id=state.loop_id)

    failure_surface_summary = derive_failure_surface_summary(
        termination_reason=termination_reason,
        verdict_or_none=verdict_or_none,
        veto_history=list(state.veto_history),
        identity_diff_breakdown=identity_diff_breakdown,
        critic_history=list(state.critic_history),
        repeated_targets=repeated_targets,
    )

    rejected_strategy_id = str(uuid.uuid4())
    rejected_doc = _build_rejected_doc(
        rejected_strategy_id=rejected_strategy_id,
        state=state,
        termination_reason=termination_reason,
        verdict_or_none=verdict_or_none,
        final_iteration=final_iteration,
        iteration_artifact_ids=iteration_artifact_ids,
        failure_surface_summary=failure_surface_summary,
    )

    # Step 1: insert into rejected_strategies.
    db[_REJECTED_STRATEGIES].insert_one(rejected_doc)
    log.info(
        "rejection_path: inserted rejected_strategies doc id=%s loop_id=%s reason=%s",
        rejected_strategy_id,
        state.loop_id,
        termination_reason,
    )

    # Step 2: emit Phase 56 strategy_rejected event (lifecycle).
    # CRITICAL: no emit_strategy_yaml call here — rejected ≠ capability.
    emit_strategy_rejected(
        loop_id=state.loop_id,
        rejected_strategy_id=rejected_strategy_id,
        root_hypothesis_id=state.root_hypothesis_id,
        termination_reason=termination_reason,
        final_iteration=final_iteration,
    )
    log.info(
        "rejection_path: emitted strategy_rejected event for loop_id=%s reason=%s",
        state.loop_id,
        termination_reason,
    )

    return rejected_strategy_id


__all__ = [
    "derive_failure_surface_summary",
    "reject_strategy",
]
