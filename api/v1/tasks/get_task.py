"""Phase 48 Plan 48-09 — GET /api/v1/tasks/get_task?task_id=X polling endpoint.

REGISTER_CAPABILITY: type=tool, id=get_task, path=VM107/registry/tool/get_task.yaml

External polling endpoint for in-flight or completed refinement tasks.
Returns the state-machine view of RefinementLoopState — opaque IDs +
primitive metrics + termination state ONLY. No raw agent thoughts, no LLM
output, no streaming.

CONTEXT § Decision 17 polling shape:
    {
      "task_id": "...",
      "state": "REFINING",
      "current_iteration": 2,
      "current_stage": "BACKTESTER",
      "budget_remaining_usd": 4.12,
      "started_at": "...",
      "updated_at": "...",
      "termination_reason": null,
      "loop_id": "...",
      "loop_registry_snapshot_hash": "..."
    }

State derivation (Decision 17 RefinementTaskState 9-state enum):
    termination_reason None                            -> RUNNING / REFINING (iter==0 vs >0)
    ACCEPTED                                           -> ACCEPTED
    CRITIC_REJECT / HARD_VETO / MAX_ITERATIONS         -> REJECTED
    BUDGET_EXCEEDED_ITERATION / BUDGET_EXCEEDED_LOOP   -> BUDGET_EXCEEDED
    CONVERGENCE_STALL                                  -> CONVERGENCE_STALL
    IDENTITY_DRIFT                                     -> IDENTITY_DRIFT
    BUILD_FAILURE + 4 degraded sub-states + BUILD_FAILED -> FAILED

Path-parameter routing note (Plan 09 deviation Rule 3 — Blocking):
helpers/api.py register_api_route() uses ``/api/<path:path>`` greedy match —
curly-brace path params are NOT supported by the existing dispatcher. Until
the dispatcher is extended, the endpoint accepts ``?task_id=X`` query
parameter instead; the URL remains ``GET /api/v1/tasks/get_task``.

Env-driven config (Directive #4): no soft-get accessors anywhere in this
module. The only env-driven dependency is the Mongo handle via
helpers/mongo.py (which itself uses os.environ direct subscript).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger("vm107.api.v1.tasks.get_task")

_REFINEMENT_LOOPS = "refinement_loops"


# CONTEXT § Decision 17 termination -> RefinementTaskState mapping.
_TERMINATION_TO_STATE: dict[str, str] = {
    "ACCEPTED": "ACCEPTED",
    "CRITIC_REJECT": "REJECTED",
    "HARD_VETO": "REJECTED",
    "MAX_ITERATIONS": "REJECTED",
    "CONVERGENCE_STALL": "CONVERGENCE_STALL",
    "IDENTITY_DRIFT": "IDENTITY_DRIFT",
    "BUDGET_EXCEEDED_ITERATION": "BUDGET_EXCEEDED",
    "BUDGET_EXCEEDED_LOOP": "BUDGET_EXCEEDED",
    "BUILD_FAILURE": "FAILED",
    "BUILD_FAILED": "FAILED",
    "STRATEGY_DEGRADED": "FAILED",
    "CODE_DEGRADED": "FAILED",
    "BACKTEST_DEGRADED": "FAILED",
    "CRITIC_DEGRADED": "FAILED",
}


def _get_db() -> Any:
    """Resolve MongoDB handle. Late import — mirrors strategy/invoke.py pattern."""
    from helpers.mongo import get_mongo_db
    return get_mongo_db()


def _json_response(body: dict[str, Any], status: int) -> Response:
    return Response(
        response=json.dumps(body),
        status=status,
        mimetype="application/json",
    )


def _derive_state(termination_reason: str | None, iteration: int) -> str:
    """Decision 17 — derive RefinementTaskState from RefinementLoopState fields."""
    if termination_reason is None:
        # In-flight loop: iter==0 -> RUNNING; iter>0 -> REFINING.
        return "REFINING" if iteration > 0 else "RUNNING"
    if termination_reason in _TERMINATION_TO_STATE:
        return _TERMINATION_TO_STATE[termination_reason]
    # Unknown termination_reason (forward-compat): treat as FAILED.
    log.warning("Unknown termination_reason %r — mapping to FAILED", termination_reason)
    return "FAILED"


def _derive_current_stage(state: str, iteration: int) -> str:
    """Best-effort current-stage label.

    The polling endpoint does NOT have direct insight into which sub-step the
    worker is executing right now (the worker is opaque). We surface a coarse
    label based on the loop state for human-readability; precise per-stage
    telemetry would require Phase 56 event-stream subscription (deferred).
    """
    if state in {"ACCEPTED", "REJECTED", "BUDGET_EXCEEDED",
                 "CONVERGENCE_STALL", "IDENTITY_DRIFT", "FAILED"}:
        return "TERMINATED"
    if iteration == 0:
        return "INITIALIZING"
    return "ITERATING"


class GetTask(ApiHandler):
    """Phase 48 § Decision 17 — refinement task polling endpoint."""

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    async def process(self, input: Input, request: Request) -> Output:
        # Read task_id from query params (helpers/api.py dispatcher doesn't
        # support curly-brace path params).
        task_id: str | None = request.args.get("task_id")
        if not task_id:
            return _json_response(
                {
                    "error": "InvalidRequest",
                    "detail": "Missing required query parameter: task_id",
                },
                422,
            )

        db = _get_db()
        doc = db[_REFINEMENT_LOOPS].find_one({"task_id": task_id})
        if doc is None:
            return _json_response(
                {
                    "error": "TaskNotFound",
                    "detail": f"task_id={task_id!r} not found in refinement_loops.",
                },
                404,
            )

        # Derive state-machine view — opaque IDs + primitive metrics ONLY.
        termination_reason = doc.get("termination_reason")
        iteration = doc.get("iteration", 0)
        state = _derive_state(termination_reason, iteration)

        budget_snapshot = doc.get("budget_snapshot") or {}
        budget_remaining_usd = budget_snapshot.get("loop_budget_remaining_usd")

        body = {
            "task_id": task_id,
            "state": state,
            "current_iteration": iteration,
            "current_stage": _derive_current_stage(state, iteration),
            "budget_remaining_usd": budget_remaining_usd,
            "started_at": doc.get("started_at"),
            "updated_at": doc.get("updated_at"),
            "termination_reason": termination_reason,
            "loop_id": doc.get("_id") or doc.get("loop_id"),
            "loop_registry_snapshot_hash": doc.get("loop_registry_snapshot_hash"),
        }
        return _json_response(body, 200)
