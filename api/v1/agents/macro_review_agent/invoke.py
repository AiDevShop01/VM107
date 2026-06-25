"""Phase 91 Plan 6 — POST /api/v1/agents/macro_review_agent/invoke

REQ-91-9 endpoint. VM100's AgentWebhookChannel POSTs alert payloads here when
liquidity_critical or regime_change fires; the agent runs synchronous review
and returns findings + optional follow-up alert_candidate emissions.

Auto-discovered by VM107's helpers.api.register_api_route from this file path
(maps to /api/v1/agents/macro_review_agent/invoke). No Blueprint required.

Security (Bearer auth — per cross_vm_contracts.py VM100_TO_VM107 emitter
scheme, NOT the X-API-KEY pattern used by other VM107 endpoints):

  - Authorization: Bearer ${VM107_API_TOKEN} — required
  - Token validated inline; no requires_api_key decorator (which expects
    X-API-KEY). VM107_API_TOKEN ≠ VM107_INTERNAL_TOKEN.
  - 401 on missing/invalid token; never leaks the expected token.
  - Session auth NOT used; CSRF disabled (M2M endpoint).

Input body (JSON):
    {
      "profile_id": str,             # required — 'macro_review_agent'
      "alert_trigger_id": int,        # required
      "alert_type": str,              # required — 'liquidity' or 'regime'
      "severity": str,                # required — 'critical' or 'regime_change'
      "subject_id": str,
      "payload": dict,
      "agent_chain_depth": int,
      "parent_dispatch_id": int | None,
      "event_id": str,
    }

Output (200): MacroReviewAgent.review_alert() return dict —
    {status, agent_id, alert_trigger_id, findings, follow_up_count,
     follow_up_alert_types, agent_chain_depth, event_id, reviewed_at}

Output (401): {"error": "Bearer token required"} or
              {"error": "Invalid Bearer token"}

Output (422): {"error": "Missing required field", "detail": <field>}

Output (500): {"error": "Internal server error", "detail": <ExceptionTypeName>}
"""
from __future__ import annotations

import json
import logging
import os

from flask import Response, request

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger(__name__)


_REQUIRED_FIELDS = ("alert_trigger_id", "alert_type", "severity")


def _bearer_token_from_request() -> str | None:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    return auth[len("Bearer "):].strip() or None


class MacroReviewAgentInvoke(ApiHandler):
    """POST /api/v1/agents/macro_review_agent/invoke — synchronous review."""

    @classmethod
    def requires_api_key(cls) -> bool:
        # We do our own Bearer validation in process() — bypass the
        # X-API-KEY decorator so the Bearer-only client (VM100) works.
        return False

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # Bearer-only M2M

    @classmethod
    def requires_csrf(cls) -> bool:
        return False  # M2M

    async def process(self, input: Input, request: Request) -> Output:
        # ── Bearer auth gate ─────────────────────────────────────────────
        expected_token = os.environ.get("VM107_API_TOKEN")
        if not expected_token:
            log.error(
                "macro_review_agent.invoke called but VM107_API_TOKEN env var "
                "is not set — refusing all requests"
            )
            return Response(
                response=json.dumps({"error": "Server token misconfigured"}),
                status=500,
                mimetype="application/json",
            )

        token = _bearer_token_from_request()
        if token is None:
            return Response(
                response=json.dumps({"error": "Bearer token required"}),
                status=401,
                mimetype="application/json",
            )
        if token != expected_token:
            return Response(
                response=json.dumps({"error": "Invalid Bearer token"}),
                status=401,
                mimetype="application/json",
            )

        # ── Field validation ─────────────────────────────────────────────
        for field in _REQUIRED_FIELDS:
            if field not in input or input.get(field) in (None, ""):
                return Response(
                    response=json.dumps({
                        "error": "Missing required field",
                        "detail": field,
                    }),
                    status=422,
                    mimetype="application/json",
                )

        # ── Late import (matches sibling per-agent invoke endpoints) ─────
        from agents.macro_review_agent.agent import review_alert

        try:
            result = review_alert(
                alert_trigger_id=int(input["alert_trigger_id"]),
                alert_type=str(input["alert_type"]),
                severity=str(input["severity"]),
                subject_id=str(input.get("subject_id", "")),
                payload=dict(input.get("payload") or {}),
                agent_chain_depth=int(input.get("agent_chain_depth", 1)),
                parent_dispatch_id=input.get("parent_dispatch_id"),
                event_id=str(input.get("event_id", "")),
            )
            return Response(
                response=json.dumps(result),
                status=200,
                mimetype="application/json",
            )

        except Exception as exc:
            log.error(
                "macro_review_agent invoke error: %s(%s)",
                type(exc).__name__,
                exc,
            )
            return Response(
                response=json.dumps({
                    "error": "Internal server error",
                    "detail": type(exc).__name__,
                }),
                status=500,
                mimetype="application/json",
            )
