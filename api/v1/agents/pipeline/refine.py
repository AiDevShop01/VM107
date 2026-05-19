"""Phase 48 Plan 48-09 — POST /api/v1/agents/pipeline/refine.

REGISTER_CAPABILITY: type=service, id=refinement_pipeline_endpoint, path=VM107/registry/service/refinement_pipeline_endpoint.yaml

External HTTP entry surface for the refinement orchestrator. Async-only;
returns 202 + {task_id, loop_id, started_at} immediately and dispatches the
loop via Phase 42 scheduler.

CONTEXT § Decision 16 (entry surface):
    Request shape:
        {"hypothesis_id": "...", "schema_version": 1, "async": true}
    Hard-fails:
        - hypothesis_id missing from hypotheses collection -> 404
        - schema_version != 1 -> 422 SchemaVersionMismatchError
        - async != true -> 422 (V1 async-only per Decision 17)
        - body missing required fields -> 422
    Response:
        202 Accepted + {"task_id": "...", "loop_id": "...", "started_at": "..."}

CONTEXT § Decision 18 (Phase 56 event sourcing):
    Endpoint emits ``refinement_loop_started`` IMMEDIATELY after validation,
    BEFORE returning the 202 response. The HTTP entry surface emits exactly
    one event; main_loop (the worker) emits the rest from worker context.
    Sole-emitter invariant: this is the ONLY refinement event the endpoint
    emits — every other lifecycle event flows through main_loop.

Env-driven config (NO fallbacks per Directive #4):
    This endpoint reads NO environment variables directly. Downstream
    dependencies (phase56_client → VM100_INTERNAL_BASE_URL; scheduler_dispatch
    → VM107_REFINEMENT_WORKER_MAX_THREADS) read their own env vars via direct
    subscript at call time.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request
from core.contracts.exceptions import SchemaVersionMismatchError

log = logging.getLogger("vm107.api.v1.agents.pipeline.refine")

EXPECTED_SCHEMA_VERSION = 1
_HYPOTHESES = "hypotheses"


def _get_db() -> Any:
    """Resolve MongoDB handle. Late import — mirrors strategy/invoke.py pattern."""
    from helpers.mongo import get_mongo_db
    return get_mongo_db()


def _utc_now_iso() -> str:
    """UTC timestamp as ISO 8601 with 'Z' suffix (Phase 56 convention)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _json_response(body: dict[str, Any], status: int) -> Response:
    return Response(
        response=json.dumps(body),
        status=status,
        mimetype="application/json",
    )


class PipelineRefine(ApiHandler):
    """Phase 48 § Decision 16 — async-only refinement loop entry."""

    @classmethod
    def requires_api_key(cls) -> bool:
        return True  # X-API-KEY required (matches strategy/invoke.py)

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: Input, request: Request) -> Output:
        # 1. Validate body shape.
        if not isinstance(input, dict):
            return _json_response(
                {"error": "InvalidBody", "detail": "Request body must be a JSON object."},
                422,
            )

        hypothesis_id = input.get("hypothesis_id")
        schema_version = input.get("schema_version")
        async_flag = input.get("async")

        if not isinstance(hypothesis_id, str) or not hypothesis_id:
            return _json_response(
                {
                    "error": "InvalidBody",
                    "detail": "Missing or invalid required field: hypothesis_id (str).",
                },
                422,
            )

        # 2. schema_version mismatch — hard fail before any side-effect.
        if schema_version != EXPECTED_SCHEMA_VERSION:
            err = SchemaVersionMismatchError(
                expected=EXPECTED_SCHEMA_VERSION,
                received=schema_version if isinstance(schema_version, int) else 0,
            )
            return _json_response(
                {"error": "SchemaVersionMismatchError", "detail": str(err)},
                422,
            )

        # 3. V1 async-only per CONTEXT § Decision 17 — reject async=false.
        if async_flag is not True:
            return _json_response(
                {
                    "error": "AsyncOnlyV1",
                    "detail": (
                        "V1 of /pipeline/refine is async-only. Refinement loops "
                        "are 5-20+ minute cognition workflows; sync HTTP "
                        "invocation is not supported. Set 'async': true."
                    ),
                },
                422,
            )

        # 4. Hypothesis existence check — 404 if missing, no side effects.
        db = _get_db()
        hypothesis_doc = db[_HYPOTHESES].find_one({"_id": hypothesis_id})
        if hypothesis_doc is None:
            return _json_response(
                {
                    "error": "HypothesisNotFound",
                    "detail": f"hypothesis_id={hypothesis_id!r} not found in {_HYPOTHESES!r}.",
                },
                404,
            )

        # 5. Allocate loop_id + task_id.
        loop_id = f"loop_{uuid.uuid4().hex}"
        task_id = f"task_{uuid.uuid4().hex}"
        started_at = _utc_now_iso()

        # 6. Persist initial RefinementLoopState (Pattern 51: persist BEFORE emit).
        # Late import to allow tests to monkeypatch the orchestrator surface.
        from core.agents.refinement_orchestrator.checkpoint import resume_or_initialize

        try:
            state = resume_or_initialize(
                db,
                loop_id=loop_id,
                hypothesis_id=hypothesis_id,
                task_id=task_id,
            )
        except Exception as exc:
            log.exception("Failed to initialize RefinementLoopState: %s", exc)
            return _json_response(
                {
                    "error": "InternalError",
                    "detail": f"Failed to initialize loop state: {exc}",
                },
                500,
            )

        # 7. Emit refinement_loop_started — MUST fire BEFORE 202 response built.
        # CONTEXT § Decision 16 + Pattern 51 (Phase 56 atomic emit).
        # Late import — tests monkeypatch the emit at this module path.
        from core.events import refinement_events as _refinement_events

        try:
            _refinement_events.emit_refinement_loop_started(
                loop_id=loop_id,
                task_id=task_id,
                root_hypothesis_id=hypothesis_id,
                strategy_family=state.strategy_family,
                registry_snapshot_hash=state.loop_registry_snapshot_hash,
            )
        except Exception as exc:
            # Emit failure is non-fatal at endpoint level (Phase 56 retries
            # internally); log and continue. main_loop will surface persistent
            # event-store outages via BUILD_FAILURE termination.
            log.warning(
                "emit_refinement_loop_started raised at endpoint (continuing): %s",
                exc,
            )

        # 8. Dispatch loop worker via Phase 42 scheduler.
        # Late import — tests monkeypatch this module-path target.
        from core.agents.refinement_orchestrator import scheduler_dispatch

        try:
            scheduler_dispatch.enqueue_refinement_worker(
                loop_id=loop_id,
                task_id=task_id,
                hypothesis_id=hypothesis_id,
            )
        except Exception as exc:
            # Dispatch failure is fatal — the loop will never run. 503 surfaces
            # the operational degradation to the caller.
            log.error("Failed to enqueue refinement worker: %s", exc)
            return _json_response(
                {
                    "error": "DispatchFailed",
                    "detail": f"Failed to enqueue refinement worker: {exc}",
                    "loop_id": loop_id,
                    "task_id": task_id,
                },
                503,
            )

        # 9. Return 202 + identifiers.
        return _json_response(
            {
                "task_id": task_id,
                "loop_id": loop_id,
                "started_at": started_at,
            },
            202,
        )
