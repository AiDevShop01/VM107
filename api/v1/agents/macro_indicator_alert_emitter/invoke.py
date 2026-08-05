"""POST /api/v1/agents/macro_indicator_alert_emitter/invoke

Phase 91 Wave 2 — the missing HTTP half of vm107.macro_indicator_alert_emitter.
The agent business logic (tier evaluation + envelope emission) already ships in
``agents/macro_indicator_alert_emitter``; this endpoint is the thin M2M doormat
the Dagster ``macro_indicator_alert_dispatch`` asset POSTs to on every FRED
Tier-1 macro release. Without it the invoke resolved to a nonexistent handler
file and returned 404 on every release (feature shipped half-wired since P91).

Auto-discovered by VM107's register_api_route() from this file path
(maps to /api/v1/agents/macro_indicator_alert_emitter/invoke). No Blueprint.

Security (mirrors the X-API-KEY siblings macro_historical_analyst /
macro_relationship_discovery — NOT the Bearer scheme used by macro_review_agent):
- requires_api_key() = True: X-API-KEY header required. The Dagster caller sends
  X-API-KEY: ${VM107_INTERNAL_TOKEN} (see macro_indicator_alert_dispatch.py).
- requires_auth() = False, requires_csrf() = False: machine-to-machine.

Input body (JSON — the shape the dispatch asset sends):
    {
      "profile_id": "vm107.macro_indicator_alert_emitter",   # informational
      "message": "emit_for_release",                          # informational
      "run_mode": "sync",                                     # informational
      "release_event": {                                       # required
        "indicator_id": str,     # e.g. "CPIAUCSL"
        "release_date": str,
        "value": float,
        "prev_value": float | None,
        "consensus": float | None,
        "history_30y": list | None,
      }
    }

Output (200): emit_for_release() return dict —
    {indicator_id, release_date, emitted_count, matched_condition_ids,
     skipped_no_indicator}

Output (422): {"error": ...} — missing/malformed release_event
Output (500): {"error": "Internal server error", "detail": <ExceptionTypeName>}
"""
from __future__ import annotations

import json
import logging

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger(__name__)


class MacroIndicatorAlertEmitterInvoke(ApiHandler):
    """POST /api/v1/agents/macro_indicator_alert_emitter/invoke — emit tier envelopes for a FRED release."""

    @classmethod
    def requires_api_key(cls) -> bool:
        return True  # X-API-KEY required (machine-to-machine from Dagster)

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # Session auth not needed for M2M

    @classmethod
    def requires_csrf(cls) -> bool:
        return False  # No CSRF for API-key-authenticated M2M endpoint

    async def process(self, input: Input, request: Request) -> Output:
        # ── Field validation ─────────────────────────────────────────────
        release_event = input.get("release_event")
        if not isinstance(release_event, dict) or not release_event:
            return Response(
                response=json.dumps({
                    "error": "Missing or malformed required field",
                    "detail": "release_event (non-empty object)",
                }),
                status=422,
                mimetype="application/json",
            )

        # ── Late import (matches sibling per-agent invoke endpoints — lets
        #    tests patch emit_alert_candidate without a module-level bind) ──
        from agents.macro_indicator_alert_emitter import emit_for_release

        try:
            # emit_for_release is deterministic + self-guarding: a missing
            # indicator_id returns skipped_no_indicator=True (not an error),
            # and per-envelope emit failures are swallowed internally. So a
            # 200 here means "release processed", and the body's emitted_count
            # / matched_condition_ids tell the asset what actually fired.
            result = emit_for_release(release_event)
            return Response(
                response=json.dumps(result),
                status=200,
                mimetype="application/json",
            )

        except Exception as exc:  # noqa: BLE001
            log.error(
                "macro_indicator_alert_emitter invoke error: %s(%s)",
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
