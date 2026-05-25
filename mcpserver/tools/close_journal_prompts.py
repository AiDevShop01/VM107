"""mission.close.journal_prompts MCP tool (Phase 67 Plan 12 — REQ-67-4).

Wraps the CLOSE-state ReflectionPromptSet emitter (Plan 07) by calling the
VM100 backend chokepoint endpoint at /api/mission-control/close/reflection-prompts.

The VM100 proxy endpoint that this tool calls is wired in Plan 13; this
plan ships the MCP-side surface so Claude Desktop / Cursor can discover
the tool. End-to-end real-data validation is in Plan 13.

Architecture lock (CONTEXT.md §3):
- MCP tools MUST route through VM100 — they NEVER bypass the privacy
  chokepoint or the auth machinery. This wrapper just forwards via httpx
  with a service-to-service bearer token.
- Env-driven config + fail-fast on missing (Phase 47.3 lock).
"""
from __future__ import annotations

import os

import httpx

from ..server import mcp

# Service-to-service config — fail-fast on missing (CLAUDE.md env lock).
VM100_BASE_URL = os.environ["VM100_BASE_URL"]
VM100_INTERNAL_TOKEN = os.environ["VM100_INTERNAL_TOKEN"]

# Generous timeout — reflection prompt assembly is multi-stage (4 assemblers
# + scoring + diversity + coherence) and may hit LLM enrichment when novelty
# crosses. 30s matches the morning_brief client default on VM100.
_HTTP_TIMEOUT_SEC = 30.0


@mcp.tool(
    name="mission.close.journal_prompts",
    description=(
        "Return the 4 reflection prompts for the user's CLOSE state — "
        "deterministic-first with optional LLM enrichment when novelty crosses. "
        "Routes through the VM100 backend chokepoint (privacy + audit preserved)."
    ),
)
async def mission_close_journal_prompts(account_id: int, date: str) -> dict:
    """Fetch the CLOSE-state reflection prompt set for a session.

    Args:
        account_id: numeric trading account id
        date: ISO YYYY-MM-DD session date

    Returns:
        ReflectionPromptSetContract serialised as dict — see VM107 Plan 07
        SUMMARY for the wire shape (selected_prompts + rejected_candidates
        + reflection_set_coherence_score + dominant_session_theme).
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
        r = await client.get(
            f"{VM100_BASE_URL}/api/mission-control/close/reflection-prompts",
            params={"account_id": account_id, "date": date},
            headers={"Authorization": f"Bearer {VM100_INTERNAL_TOKEN}"},
        )
        r.raise_for_status()
        return r.json()
