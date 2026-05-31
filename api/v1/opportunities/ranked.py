"""VM107 ApiHandler — GET /api/v1/opportunities/ranked

Phase 66 Plan 66-06 — Tier-Ranked Opportunity endpoint.

Route auto-registered via the `api/<path:path>` dispatcher in helpers/api.py.
File path `api/v1/opportunities/ranked.py` maps to URL `/api/v1/opportunities/ranked`.

Query parameters:
    state   (required) — trading session state: pre|open|mid|close|active_supervision
    account (required) — account ID (integer)
    session (optional) — session universe key; default 'london_ny_fx'

Returns:
    200 — OpportunityRankingSnapshotContract-shaped JSON dict
    400 — {"error": "state and account required"} when either is absent

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


class OpportunitiesRankedHandler(ApiHandler):
    """GET /api/v1/opportunities/ranked?state=<state>&account=<id>&session=<session>"""

    @classmethod
    def requires_auth(cls) -> bool:
        # Phase 73-followup: service-to-service token replaces session-cookie auth.
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_csrf(cls) -> bool:
        # GET requests are read-only; skip CSRF.
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        # Extract query-string params (GET requests arrive via request.args)
        state = request.args.get("state") or input.get("state")
        account = request.args.get("account") or input.get("account")
        session = (
            request.args.get("session")
            or input.get("session", "london_ny_fx")
        )

        if not state or not account:
            return Response(
                response='{"error": "state and account required"}',
                status=400,
                mimetype="application/json",
            )

        try:
            account_id = int(account)
        except (ValueError, TypeError):
            return Response(
                response='{"error": "account must be a valid integer"}',
                status=400,
                mimetype="application/json",
            )

        from emitters.opportunity_ranker import OpportunityRanker

        try:
            ranker = OpportunityRanker()
            snapshot = ranker.emit(
                state=state,
                account_id=account_id,
                session=session,
            )
        except Exception as exc:
            log.error(
                "OpportunitiesRankedHandler: OpportunityRanker.emit failed: %s",
                exc,
                exc_info=True,
            )
            return Response(
                response='{"error": "opportunity ranking failed", "degraded_mode": true}',
                status=500,
                mimetype="application/json",
            )

        return snapshot
