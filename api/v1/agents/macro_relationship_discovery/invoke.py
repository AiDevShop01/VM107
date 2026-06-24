"""Phase 89.2 Plan 04 — POST /api/v1/agents/macro_relationship_discovery/invoke

HTTP endpoint for the macro_relationship_discovery scheduled background agent
(REQ-89.2-2). Wraps :meth:`agents.macro_relationship_discovery.agent.MacroRelationshipDiscovery.run`
behind a per-agent invoke surface mirroring the sibling pattern at
``api/v1/agents/macro_historical_analyst/invoke.py``.

Auto-discovered by VM107's :func:`helpers.api.register_api_route` from the file
path ``api/v1/agents/macro_relationship_discovery/invoke.py`` (maps directly to
``/api/v1/agents/macro_relationship_discovery/invoke``). No Flask Blueprint /
``add_url_rule`` is required — file-path-to-URL discovery handles routing.

The generic dispatch endpoint ``/api/v1/agents/run`` (Plan 05) is intentionally
NOT implemented here; this file ships only the per-agent invoke surface.

Security (M2M from Dagster nightly schedule):
    - ``requires_api_key() = True``  — ``X-API-KEY`` header validated against
      env ``VM107_INTERNAL_TOKEN`` by the :func:`helpers.api.requires_api_key`
      decorator BEFORE :meth:`process` runs.
    - ``requires_auth()    = False`` — no session auth for machine-to-machine.
    - ``requires_csrf()    = False`` — no CSRF for API-key-authenticated M2M.

Input body (JSON):
    {
      "message":  str,  # optional — defaults to "run nightly scan"
      "run_mode": str,  # optional — defaults to "scheduled"
    }

Output (200): :meth:`MacroRelationshipDiscovery.run` return dict — exact 3 keys
    {"proposals_created": int, "scan_duration_s": float, "throughput_action": str}

Output (422): {"error": "Invalid payload", "detail": <reason>}
    Returned when ``message`` or ``run_mode`` is provided but is not a string.

Output (500): {"error": "Internal server error", "detail": <ExceptionTypeName>}
    Returned when the underlying agent ``.run()`` raises. The detail field is
    the exception class name only — no stack-trace leak (matches sibling).
"""
from __future__ import annotations

import json
import logging

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger(__name__)


class MacroRelationshipDiscoveryInvoke(ApiHandler):
    """POST /api/v1/agents/macro_relationship_discovery/invoke — invoke the discovery agent."""

    @classmethod
    def requires_api_key(cls) -> bool:
        return True  # X-API-KEY required (machine-to-machine from Dagster)

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # Session auth not needed for M2M

    @classmethod
    def requires_csrf(cls) -> bool:
        return False  # No CSRF for M2M API-key endpoint

    async def process(self, input: Input, request: Request) -> Output:
        # Extract message + run_mode with their documented defaults — the
        # agent.run() signature itself defaults these, but extracting here
        # lets us validate the payload shape before invoking.
        message = input.get("message", "run nightly scan")
        run_mode = input.get("run_mode", "scheduled")

        # Validate types — defensively reject non-string overrides. None is
        # allowed for back-compat: input.get(...) returns the default when the
        # key is absent, so isinstance failures only fire when the caller
        # explicitly supplied a wrong-typed value (int, list, dict, ...).
        if message is not None and not isinstance(message, str):
            return Response(
                response=json.dumps({
                    "error": "Invalid payload",
                    "detail": "message and run_mode must be strings",
                }),
                status=422,
                mimetype="application/json",
            )
        if run_mode is not None and not isinstance(run_mode, str):
            return Response(
                response=json.dumps({
                    "error": "Invalid payload",
                    "detail": "message and run_mode must be strings",
                }),
                status=422,
                mimetype="application/json",
            )

        # Late import — defers the agent-module env-driven fail-fast (Postgres
        # / Neo4j / VM102 env vars are read inside .run(), not at module
        # import) to call time AND lets unittest.mock.patch swap the class on
        # the agent module namespace without touching this handler's import
        # graph (matches sibling MacroHistoricalAnalystInvoke late-import).
        from agents.macro_relationship_discovery.agent import (
            MacroRelationshipDiscovery,
        )

        try:
            agent = MacroRelationshipDiscovery()
            result = agent.run(message=message, run_mode=run_mode)
            return Response(
                response=json.dumps(result),
                status=200,
                mimetype="application/json",
            )

        except Exception as e:
            # Log exception type + message; return 500 with class name only.
            # No stack trace / no raw message in the body — matches sibling
            # MacroHistoricalAnalystInvoke pattern.
            log.error(
                "macro_relationship_discovery invoke error: %s(%s)",
                type(e).__name__,
                e,
            )
            return Response(
                response=json.dumps({
                    "error": "Internal server error",
                    "detail": type(e).__name__,
                }),
                status=500,
                mimetype="application/json",
            )
