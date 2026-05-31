"""VM107 ApiHandler — GET /api/v1/intelligence_feed/discoveries

Phase 66 Plan 66-07 — DISCOVERIES IntelligenceFeed endpoint (REQ-66-3).

Route auto-registered via the `api/<path:path>` dispatcher in helpers/api.py.
File path `api/v1/intelligence_feed/discoveries.py` maps to URL
`/api/v1/intelligence_feed/discoveries`.

Query parameters:
    state   (required) — trading session state: pre|open|mid|close|active_supervision
    account (required) — account ID (integer); discoveries are account-scoped

Returns:
    200 — {"items": [...DiscoveryFeedItem serialized...]}
    400 — {"error": "state and account required"}

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


class IntelligenceFeedDiscoveriesHandler(ApiHandler):
    """GET /api/v1/intelligence_feed/discoveries?state=<state>&account=<id>"""

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
        account_raw = request.args.get("account") or input.get("account")

        if not state or not account_raw:
            return Response(
                response='{"error": "state and account required"}',
                status=400,
                mimetype="application/json",
            )

        try:
            account_id = int(account_raw)
        except (ValueError, TypeError):
            return Response(
                response='{"error": "account must be a valid integer"}',
                status=400,
                mimetype="application/json",
            )

        from emitters.intelligence_feed_discoveries_composer import (
            IntelligenceFeedDiscoveriesComposer,
        )

        try:
            composer = IntelligenceFeedDiscoveriesComposer()
            items = composer.compose(account_id=account_id, state=state)
        except Exception as exc:
            log.error(
                "IntelligenceFeedDiscoveriesHandler: compose failed: %s",
                exc,
                exc_info=True,
            )
            return {
                "items": [],
                "_demo": True,
                "degraded_mode": True,
                "error": "discoveries composer unavailable",
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
            })

        return {"items": serialized, "_demo": len(serialized) == 0}
