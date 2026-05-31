"""VM107 ApiHandler — GET /api/v1/intelligence_feed/macro

Phase 66 Plan 66-07 — MACRO IntelligenceFeed endpoint (REQ-66-3).

Route auto-registered via the `api/<path:path>` dispatcher in helpers/api.py.
File path `api/v1/intelligence_feed/macro.py` maps to URL
`/api/v1/intelligence_feed/macro`.

Query parameters:
    state   (required) — trading session state: pre|open|mid|close|active_supervision
    account (optional) — account ID (integer); some macro items are account-agnostic

Returns:
    200 — {"items": [...MacroIntelligenceFeedItem serialized...]}
    400 — {"error": "state required"}

Auth: X-API-KEY service token (Phase 73-followup VM100↔VM107 service auth).
      Session-cookie auth disabled — service-to-service callers do not have
      a Flask session. Optional Bearer JWT is audit-logged but not trusted.
"""
from __future__ import annotations

import logging

from helpers.api import ApiHandler, Response

try:
    from flask import Request
except ImportError:
    from werkzeug.wrappers import Request  # type: ignore[no-redef,assignment]

log = logging.getLogger(__name__)


class IntelligenceFeedMacroHandler(ApiHandler):
    """GET /api/v1/intelligence_feed/macro?state=<state>&account=<id>"""

    @classmethod
    def requires_auth(cls) -> bool:
        # Phase 73-followup: service-to-service token replaces session-cookie auth.
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        state = request.args.get("state") or input.get("state")
        if not state:
            return Response(
                response='{"error": "state required"}',
                status=400,
                mimetype="application/json",
            )

        account_id = None
        account_raw = request.args.get("account") or input.get("account")
        if account_raw is not None:
            try:
                account_id = int(account_raw)
            except (ValueError, TypeError):
                return Response(
                    response='{"error": "account must be a valid integer"}',
                    status=400,
                    mimetype="application/json",
                )

        from emitters.intelligence_feed_macro_composer import IntelligenceFeedMacroComposer

        try:
            composer = IntelligenceFeedMacroComposer()
            items = composer.compose()
        except Exception as exc:
            log.error(
                "IntelligenceFeedMacroHandler: compose failed: %s",
                exc,
                exc_info=True,
            )
            return {
                "items": [],
                "_demo": True,
                "degraded_mode": True,
                "error": "macro composer unavailable",
            }

        serialized = []
        for item in items:
            serialized.append({
                "item_id": item.item_id,
                "category": item.category,
                "priority": item.priority,
                "title": item.title,
                "summary": item.summary,
                "evidence": item.evidence,
                "confidence": item.confidence,
                "generated_at": item.generated_at.isoformat(),
                "source_emitter": item.source_emitter,
                "state": item.state,
                "lifecycle_state": item.lifecycle_state,
                "llm_enriched": item.llm_enriched,
            })

        return {"items": serialized, "_demo": len(serialized) == 0}
