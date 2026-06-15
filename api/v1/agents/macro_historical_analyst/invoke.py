"""Phase 86 Plan 07 — POST /api/v1/agents/macro_historical_analyst/invoke

HTTP endpoint for macro_historical_analyst agent invocation.

Auto-discovered by VM107's register_api_route() from api/v1/agents/macro_historical_analyst/invoke.py
(path maps to /api/v1/agents/macro_historical_analyst/invoke).

Security:
- requires_api_key() = True: X-API-KEY header required (machine-to-machine from VM100)
- requires_auth() = False: session auth not required for M2M
- requires_csrf() = False: no CSRF for API-key-authenticated M2M endpoint

Input body: {
    "envelope": { vm102_event_study envelope },
    "result":   { event-study result with curves },
    "indicator_name": str,
    "asset_names": list[str]
}

Output (200): MacroHistoricalAnalyst.invoke() return dict
Output (422): {"error": str} — missing required fields
Output (500): {"error": str} — unexpected server error
"""
from __future__ import annotations

import json
import logging

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger(__name__)


class MacroHistoricalAnalystInvoke(ApiHandler):
    """POST /api/v1/agents/macro_historical_analyst/invoke — invoke the macro historical analyst."""

    @classmethod
    def requires_api_key(cls) -> bool:
        return True  # X-API-KEY required (machine-to-machine from VM100)

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # Session auth not needed for M2M

    @classmethod
    def requires_csrf(cls) -> bool:
        return False  # No CSRF for M2M API-key endpoint

    async def process(self, input: Input, request: Request) -> Output:
        # Validate required fields
        envelope = input.get("envelope")
        result = input.get("result")
        indicator_name = input.get("indicator_name")
        asset_names = input.get("asset_names")

        if not all([envelope, result, indicator_name, asset_names]):
            missing = [
                k for k, v in {
                    "envelope": envelope,
                    "result": result,
                    "indicator_name": indicator_name,
                    "asset_names": asset_names,
                }.items() if not v
            ]
            return Response(
                response=json.dumps({
                    "error": f"Missing required fields: {missing}"
                }),
                status=422,
                mimetype="application/json",
            )

        if not isinstance(asset_names, list):
            return Response(
                response=json.dumps({"error": "asset_names must be a list"}),
                status=422,
                mimetype="application/json",
            )

        # Late import — allows patching in tests without module-level bind
        from agents.macro_historical_analyst.agent import MacroHistoricalAnalyst

        try:
            agent = MacroHistoricalAnalyst()
            output = agent.invoke(
                envelope=envelope,
                indicator_name=indicator_name,
                asset_names=asset_names,
                result=result,
            )
            return Response(
                response=json.dumps(output),
                status=200,
                mimetype="application/json",
            )

        except KeyError as e:
            # Malformed envelope — 422
            return Response(
                response=json.dumps({
                    "error": "Invalid envelope shape",
                    "detail": str(e),
                }),
                status=422,
                mimetype="application/json",
            )

        except Exception as e:
            log.error(
                "macro_historical_analyst invoke error: %s(%s)",
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
