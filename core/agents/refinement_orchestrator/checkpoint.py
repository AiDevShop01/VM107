"""Phase 48 crash-recovery + resume primitives.

Implements REQ-48-D17 (resumable task state, CONTEXT § Decision 17).

Public functions:
    load_state(db, loop_id) -> RefinementLoopState | None
    resume_or_initialize(db, loop_id, hypothesis_id, task_id) -> RefinementLoopState

A re-instantiated orchestrator reads RefinementLoopState back from Mongo and
resumes from the recorded iteration without re-running completed iterations.
The envelope chain (Phase 44 ``source_envelope_id``) acts as the idempotency
key — already-completed iterations have envelopes; resumption skips them.

Plan 48-04 + 48-05 build the loop-control logic on top of these primitives.
"""
from __future__ import annotations

from typing import Any

from core.contracts.schemas import RefinementLoopState

_REFINEMENT_LOOPS = "refinement_loops"


_TERMINAL_REASONS: frozenset[str] = frozenset(
    {
        "ACCEPTED",
        "CRITIC_REJECT",
        "HARD_VETO",
        "IDENTITY_DRIFT",
        "CONVERGENCE_STALL",
        "BUDGET_EXCEEDED_ITERATION",
        "BUDGET_EXCEEDED_LOOP",
        "MAX_ITERATIONS",
        "BUILD_FAILURE",
        # Plan 48-01 sub-states:
        "CRITIC_DEGRADED",
        "STRATEGY_DEGRADED",
        "CODE_DEGRADED",
        "BUILD_FAILED",
        "BACKTEST_DEGRADED",
    }
)


def load_state(db: Any, loop_id: str) -> RefinementLoopState | None:
    """Read the RefinementLoopState doc back from Mongo. Returns None if absent.

    The doc was persisted via ``state.initialize_loop_state`` which writes
    Pydantic's ``model_dump(mode="json")`` — datetime fields are ISO strings.
    ``RefinementLoopState.model_validate(doc)`` coerces them back to datetime.
    """
    doc = db[_REFINEMENT_LOOPS].find_one({"_id": loop_id})
    if doc is None:
        return None
    # Drop Mongo-internal keys that aren't on the Pydantic schema.
    doc = {k: v for k, v in doc.items() if k not in {"_id", "task_id"}}
    return RefinementLoopState.model_validate(doc)


def resume_or_initialize(
    db: Any,
    *,
    loop_id: str,
    hypothesis_id: str,
    task_id: str,
) -> RefinementLoopState:
    """Idempotent loop-entry point — returns the live state, creating it if absent.

    Behavior:
      - If a RefinementLoopState exists for ``loop_id`` AND its
        ``termination_reason`` is None (non-terminal), return it.
      - If a state exists with a terminal ``termination_reason``, return it
        unchanged — the caller (Plan 48-04) decides whether to start a new
        loop under a different loop_id.
      - If no state exists, call ``initialize_loop_state`` to create one.
    """
    existing = load_state(db, loop_id)
    if existing is not None:
        return existing

    # Late import to avoid circular surface within the package.
    from core.agents.refinement_orchestrator.state import initialize_loop_state

    return initialize_loop_state(
        db,
        loop_id=loop_id,
        hypothesis_id=hypothesis_id,
        task_id=task_id,
    )


def is_terminal(state: RefinementLoopState) -> bool:
    """Return True if the loop has already terminated."""
    return state.termination_reason in _TERMINAL_REASONS
