"""Phase 44 — POST /api/v1/agents/strategy/invoke

External entry point for direct Strategy Agent invocation with a manually-crafted
Hypothesis. The endpoint is source-agnostic per CONTEXT § Strategy Agent — any caller
with a valid Hypothesis can invoke.

Sync path (default): validate Hypothesis → run_strategy → safe_parse already done
inside run_strategy → return StrategySpec + meta. 30s default timeout (configurable
via STRATEGY_SYNC_TIMEOUT_S env var; hard cap 60s).

Async path (?async=true): generate task_id and return 202 + {task_id}. Polling
endpoint (GET /api/v1/tasks/{task_id}) is out of Phase 44 scope per Research § OQ-1.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

from flask import Response, jsonify
from pydantic import ValidationError

from helpers.api import ApiHandler, Input, Output, Request
from core.contracts.schemas import Hypothesis
from core.contracts.exceptions import SchemaVersionMismatchError
from core.agents.invocation_exceptions import (
    StrategyAgentDegradedError,
    InvalidInputError,
)

# run_strategy is imported lazily (inside process) so that
# `patch("core.agents.invocation.run_strategy", ...)` works in tests.
# Module-level `from core.agents.invocation import run_strategy` would bind the
# function at load time into this module's local namespace and the patch would
# not be visible to the already-bound reference.

log = logging.getLogger(__name__)

SYNC_TIMEOUT_SECONDS_DEFAULT = 30
SYNC_TIMEOUT_SECONDS_HARD_CAP = 60
EXPECTED_HYPOTHESIS_SCHEMA_VERSION = 1


def _get_db():
    """Resolve MongoDB client. Mirrors helpers/mongo.py pattern."""
    from helpers.mongo import get_mongo_db  # late import — helpers depends on settings
    return get_mongo_db()


def _build_meta(
    envelope_id: str,
    source_envelope_id: str | None,
    *,
    model_used: str,
    fallback_used: bool,
    duration_ms: int,
) -> dict:
    return {
        "envelope_id": envelope_id,
        "source_envelope_id": source_envelope_id,
        "agent_id": "strategy_agent",
        "model_used": model_used,
        "fallback_used": fallback_used,
        "duration_ms": duration_ms,
    }


class StrategyInvoke(ApiHandler):
    @classmethod
    def requires_api_key(cls) -> bool:
        return True  # X-API-KEY required (machine-to-machine; matches existing VM107 endpoints)

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # session auth not required

    @classmethod
    def requires_csrf(cls) -> bool:
        return False  # no CSRF for API-key-authenticated machine-to-machine endpoint

    async def process(self, input: Input, request: Request) -> Output:
        # 1. Parse async query param
        async_mode = request.args.get("async", "").lower() in ("true", "1", "yes")

        # 2. Validate Hypothesis
        hypothesis_dict = input.get("hypothesis") if isinstance(input, dict) else None
        if hypothesis_dict is None or not isinstance(hypothesis_dict, dict):
            return Response(
                response=json.dumps({"error": "Missing required field: hypothesis"}),
                status=422,
                mimetype="application/json",
            )
        try:
            hypothesis = Hypothesis.model_validate(hypothesis_dict)
        except ValidationError as ve:
            return Response(
                response=json.dumps({
                    "error": "Invalid Hypothesis",
                    "validation_errors": ve.errors(),
                }),
                status=422,
                mimetype="application/json",
            )

        # 3. Strict schema_version check (Phase 44 fail-fast)
        if hypothesis.schema_version != EXPECTED_HYPOTHESIS_SCHEMA_VERSION:
            err = SchemaVersionMismatchError(
                expected=EXPECTED_HYPOTHESIS_SCHEMA_VERSION,
                received=hypothesis.schema_version,
            )
            return Response(
                response=json.dumps({
                    "error": "SchemaVersionMismatchError",
                    "detail": str(err),
                }),
                status=422,
                mimetype="application/json",
            )

        # 4. Async branch — generate task_id placeholder, return 202.
        # NOTE: Full Phase 42 task creation is out of scope (Research § OQ-1); for now
        # we generate the task_id and return it. Polling endpoint deferred.
        if async_mode:
            task_id = f"api-{uuid.uuid4().hex}"
            return Response(
                response=json.dumps({"task_id": task_id, "status": "pending"}),
                status=202,
                mimetype="application/json",
            )

        # 5. Sync branch — invoke with timeout
        timeout_s = min(
            int(os.getenv("STRATEGY_SYNC_TIMEOUT_S", str(SYNC_TIMEOUT_SECONDS_DEFAULT))),
            SYNC_TIMEOUT_SECONDS_HARD_CAP,
        )
        task_id = f"api-{uuid.uuid4().hex}"
        db = _get_db()
        start = time.perf_counter()

        # Late import — allows patch("core.agents.invocation.run_strategy", ...) in tests.
        from core.agents.invocation import run_strategy as _run_strategy

        try:
            # run_strategy is synchronous — run in executor to apply timeout
            loop = asyncio.get_event_loop()
            strategy_spec = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _run_strategy(hypothesis, db=db, task_id=task_id),
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            # Per CONTEXT.md "planner picks": return 408 (simpler than auto-async
            # since polling endpoint absent — Research § OQ-1)
            return Response(
                response=json.dumps({
                    "error": "Sync timeout exceeded",
                    "timeout_s": timeout_s,
                    "hint": "retry with ?async=true",
                }),
                status=408,
                mimetype="application/json",
            )
        except (StrategyAgentDegradedError, InvalidInputError) as e:
            # 502 — Strategy Agent failed to produce typed output.
            # Write a status=failure summary envelope.
            from core.agents.envelope_writer import build_envelope, write_envelope
            envelope = build_envelope(
                task_id=task_id,
                parent_task_id=None,
                agent_id="strategy_agent",
                input_payload=hypothesis.model_dump(),
                output_payload={"error": type(e).__name__, "detail": str(e)},
                telemetry={},
                status="failure",
                source_envelope_id=hypothesis.source_envelope_id,
            )
            env_id = write_envelope(db, envelope)
            return Response(
                response=json.dumps({
                    "error": type(e).__name__,
                    "detail": str(e),
                    "envelope_id": env_id,
                }),
                status=502,
                mimetype="application/json",
            )
        duration_ms = int((time.perf_counter() - start) * 1000)

        # 6. Find the envelope just persisted by run_strategy to retrieve telemetry.
        envelope_doc = db["agent_envelopes"].find_one(
            {"task_id": task_id, "agent_id": "strategy_agent", "status": "success"},
        )
        if envelope_doc is None:
            # Should not happen — run_strategy always writes — but guard anyway.
            log.error("strategy_agent envelope missing for task_id=%s", task_id)
            return Response(
                response=json.dumps({"error": "Internal: envelope persistence failure"}),
                status=500,
                mimetype="application/json",
            )

        return Response(
            response=json.dumps({
                "strategy_spec": strategy_spec.model_dump(),
                "meta": _build_meta(
                    envelope_id=envelope_doc["envelope_id"],
                    source_envelope_id=hypothesis.source_envelope_id,
                    model_used=envelope_doc.get("model_used", "unknown"),
                    fallback_used=bool(envelope_doc.get("fallback_used", False)),
                    duration_ms=duration_ms,
                ),
            }),
            status=200,
            mimetype="application/json",
        )
