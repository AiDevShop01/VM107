"""Phase 89.2 Plan 05 — POST /api/v1/agents/run

Generic agent-dispatch endpoint (REQ-89.2-3). The Dagster macro_relationship_discovery
asset (see ``fingpt_orchestration/.../assets/macro/macro_relationship_discovery.py``)
hardcodes ``POST {VM107_AGENT_URL}/api/v1/agents/run`` with a JSON body of
``{profile_id, message, run_mode}``. This module is the matching server-side
target — without it every Dagster scheduled run gets HTTP 404 from VM107.

Auto-discovered by VM107's :func:`helpers.api.register_api_route` from the file
path ``api/v1/agents/run.py`` (maps directly to ``/api/v1/agents/run``). No
Flask Blueprint / ``add_url_rule`` is required — file-path-to-URL discovery
handles routing, matching the sibling per-agent endpoints under
``api/v1/agents/<name>/invoke.py``.

Design note (LOCKED — see 89.2-RESEARCH §Missing 3 "Design note"):
    Phase 89.2 supports exactly ONE profile in the dispatch table:
    ``vm107.macro_relationship_discovery`` (the only consumer at this point in
    time). The handler uses a literal ``if/elif`` branch + 404 default rather
    than a registry-driven dynamic-import mechanism. Future agents add their
    own ``elif`` branch as they ship; the capability-registry-driven dispatch
    pattern is Phase 47.6 / 47.7 territory, not Phase 89.2. This keeps the
    surface predictable and matches the per-agent invoke pattern's late-import
    behaviour so tests can patch on the agent module namespace.

Security (M2M from Dagster scheduled job):
    - ``requires_api_key() = True``  — ``X-API-KEY`` header validated against
      env ``VM107_INTERNAL_TOKEN`` by the :func:`helpers.api.requires_api_key`
      decorator BEFORE :meth:`process` runs.
    - ``requires_auth()    = False`` — no session auth for machine-to-machine.
    - ``requires_csrf()    = False`` — no CSRF for API-key-authenticated M2M.

Input body (JSON):
    {
      "profile_id": str,  # required — agent profile to dispatch to
      "message":    str,  # optional — defaults to ""
      "run_mode":   str,  # optional — defaults to "scheduled"
    }

Output (200): The dispatched agent's ``.run()`` return dict, encoded verbatim.
    For ``vm107.macro_relationship_discovery`` that is:
    ``{"proposals_created": int, "scan_duration_s": float, "throughput_action": str}``.

Output (404): ``{"error": "Unknown agent profile: <profile_id>"}``
    Returned when ``profile_id`` is not in :data:`SUPPORTED_PROFILES`.

Output (422): ``{"error": "profile_id is required"}``
    Returned when the ``profile_id`` field is absent / ``None``.

Output (500): ``{"error": "Internal server error", "detail": <ExceptionTypeName>}``
    Returned when the dispatched agent's ``.run()`` raises. The detail field
    is the exception class name only — no stack-trace leak (matches the per-
    agent invoke handler's 500 contract).

Upstream caller:
    ``fingpt_orchestration/src/fingpt_orchestration/assets/macro/macro_relationship_discovery.py``
    (function ``_dispatch_agent_sync``) — issues a 1800s-timeout
    ``requests.post`` with ``profile_id="vm107.macro_relationship_discovery"``.
"""
from __future__ import annotations

import json
import logging

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger(__name__)

# Phase 89.2 — single profile supported. Future agents add their own elif
# branch in :meth:`AgentsRun.process` below AND a new entry here. This frozen
# set exists primarily so tests / introspection callers can enumerate the
# supported surface without parsing the if/elif body.
SUPPORTED_PROFILES = frozenset({"vm107.macro_relationship_discovery"})


class AgentsRun(ApiHandler):
    """POST /api/v1/agents/run — generic dispatch by ``profile_id``."""

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
        profile_id = input.get("profile_id")
        message = input.get("message", "")
        run_mode = input.get("run_mode", "scheduled")

        # Reject missing profile_id early — 422 (Unprocessable Entity) is the
        # right status here because the request is syntactically valid JSON
        # but semantically missing a required field. 404 is reserved for
        # "the profile_id you supplied doesn't map to any agent".
        if profile_id is None:
            return Response(
                response=json.dumps({"error": "profile_id is required"}),
                status=422,
                mimetype="application/json",
            )

        if profile_id == "vm107.macro_relationship_discovery":
            # Late import — defers the agent module's env-driven fail-fast
            # (Postgres / Neo4j / VM102 env reads inside ``.run()``) to call
            # time AND lets ``unittest.mock.patch`` swap the class on the
            # agent module namespace without touching this handler's import
            # graph. Matches the per-agent invoke pattern from Plan 04.
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
                # Log exception type + message; return 500 with class name
                # only. No stack trace / no raw message in the body — matches
                # the sibling per-agent handler's 500 contract.
                log.error(
                    "agents/run dispatch error for %s: %s(%s)",
                    profile_id,
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

        # Unknown profile — 404. Future agents add their own ``elif`` branch
        # above (and update :data:`SUPPORTED_PROFILES`) rather than relying on
        # a dynamic-registry lookup at request time.
        return Response(
            response=json.dumps({
                "error": f"Unknown agent profile: {profile_id}",
            }),
            status=404,
            mimetype="application/json",
        )
