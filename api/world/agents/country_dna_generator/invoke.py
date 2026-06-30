"""Phase 96 Plan 05 — HTTP shim for the CountryDnaGenerator agent.

Exposes ``POST /api/world/agents/country_dna_generator/invoke``. Wraps the
existing ``CountryDnaGenerator.invoke(iso, profile_summary)`` and returns
the typed EconomicDnaTag list.

VM100 country_dna resolver POSTs here. The agent itself lives in
``/a0/agents/country_dna_generator_agent/`` (Plan 96-05). Without this
HTTP wrapper the agent class is unreachable from the VM100 resolver and
the ECONOMIC_DNA tab degrades to UNAVAILABLE.

Auth: requires_api_key=True per Agent-Zero convention for cross-VM HTTP.
"""
from __future__ import annotations

import logging

from helpers.api import ApiHandler, Request, Response

log = logging.getLogger(__name__)


class InvokeCountryDnaGenerator(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return False  # Service-to-service RPC; VM100 doesn't carry an API key.

    async def process(self, input: dict, request: Request) -> dict | Response:
        iso = (input or {}).get("iso") or (input or {}).get("iso_alpha2")
        profile_summary = (input or {}).get("profile_summary") or {}

        if not iso or not isinstance(iso, str) or len(iso) != 2:
            return Response(
                '{"error": "iso (alpha-2) required"}',
                status=400,
                mimetype="application/json",
            )
        iso = iso.upper()

        try:
            # Lazy import so this module loads cleanly even if NEO4J_URI /
            # QDRANT_URL aren't set during boot (the agent itself fail-fasts
            # only when actually constructed, per from_env contract).
            from agents.country_dna_generator_agent.agent import (
                CountryDnaGenerator,
            )

            agent = CountryDnaGenerator.from_env()
            tags = agent.invoke(iso, profile_summary)
            # EconomicDnaTag is a Pydantic BaseModel; serialize each.
            return {
                "iso_alpha2": iso,
                "tags": [t.model_dump(mode="json") for t in tags],
                "agent_id": CountryDnaGenerator.AGENT_ID,
            }
        except KeyError as exc:
            log.warning(
                "world.country_dna.env_missing",
                extra={"iso": iso, "missing": str(exc)},
            )
            return Response(
                f'{{"error": "env missing: {exc}"}}',
                status=503,
                mimetype="application/json",
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft surface for VM100
            log.exception(
                "world.country_dna.agent_failed",
                extra={"iso": iso, "exc_type": exc.__class__.__name__},
            )
            return Response(
                f'{{"error": "agent failed: {exc.__class__.__name__}"}}',
                status=500,
                mimetype="application/json",
            )
