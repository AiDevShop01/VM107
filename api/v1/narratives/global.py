"""VM107 ApiHandler — GET /api/v1/narratives/global

Phase 66 Plan 05 — Global Narrative endpoint.

Route auto-registered via the `api/<path:path>` dispatcher in helpers/api.py.
File path `api/v1/narratives/global.py` maps to URL `/api/v1/narratives/global`.

Query parameters:
    state           (required) — trading session state: pre|open|mid|close|active_supervision
    refresh_reason  (optional) — default SCHEDULED

Returns:
    200 — GlobalNarrativeContract-shaped JSON dict
    400 — {"error": "missing state parameter"} when state is absent

Auth: X-API-KEY service token (Phase 73-followup VM100↔VM107 service auth).
      Session-cookie auth disabled — service-to-service callers do not have
      a Flask session. Optional Bearer JWT is audit-logged but not trusted.
"""
from __future__ import annotations

from helpers.api import ApiHandler, Response

try:
    from flask import Request
except ImportError:
    from werkzeug.wrappers import Request  # type: ignore[no-redef,assignment]


class GlobalNarrativeHandler(ApiHandler):
    """GET /api/v1/narratives/global?state=<state>&refresh_reason=<reason>"""

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
        # Extract query-string params (GET requests arrive via request.args,
        # not the JSON body that ApiHandler parses into `input`).
        state = request.args.get("state") or input.get("state")
        if not state:
            return Response(
                response='{"error": "missing state parameter"}',
                status=400,
                mimetype="application/json",
            )

        refresh_reason = (
            request.args.get("refresh_reason")
            or input.get("refresh_reason", "SCHEDULED")
        )

        from emitters.global_narrative_emitter import GlobalNarrativeEmitter
        emitter = GlobalNarrativeEmitter()
        try:
            contract = emitter.get_narrative(
                state=state,
                refresh_reason=refresh_reason,
            )
        except ValueError as exc:
            return Response(
                response=f'{{"error": "{exc}"}}',
                status=400,
                mimetype="application/json",
            )

        return contract
