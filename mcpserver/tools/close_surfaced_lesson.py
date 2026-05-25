"""mission.close.surfaced_lesson MCP tool (Phase 67 Plan 12 — REQ-67-5).

Wraps the VM100 surfaced_lesson endpoint (Plan 08) — returns the
highest-confidence behavioral pattern from the user's session, with
Option A fallback to previous-session lesson + banner_text when today's
analysis hasn't run yet.

Architecture lock (CONTEXT.md §3):
- MCP tools MUST route through VM100 — privacy chokepoint + JWT auth
  remain at the VM100 boundary, NOT bypassed at the MCP server.
- Env-driven config + fail-fast on missing (Phase 47.3 lock).

Endpoint contract: GET /api/mission-control/surfaced-lesson
    params: account_id, date
    returns: SurfacedLessonContract (incl. fallback_used, _demo, banner_text)
"""
from __future__ import annotations

import os

import httpx

from ..server import mcp

VM100_BASE_URL = os.environ["VM100_BASE_URL"]
VM100_INTERNAL_TOKEN = os.environ["VM100_INTERNAL_TOKEN"]

_HTTP_TIMEOUT_SEC = 30.0


@mcp.tool(
    name="mission.close.surfaced_lesson",
    description=(
        "Return the highest-confidence behavioral pattern from the user's session "
        "(or yesterday's session with banner_text when today's analysis hasn't "
        "completed yet — Pitfall 4 Option A fallback). Routes through the "
        "VM100 backend chokepoint (privacy + audit preserved)."
    ),
)
async def mission_close_surfaced_lesson(account_id: int, date: str) -> dict:
    """Fetch the CLOSE-state surfaced lesson card for a session.

    Args:
        account_id: numeric trading account id
        date: ISO YYYY-MM-DD session date

    Returns:
        SurfacedLessonContract serialised as dict — see VM100 Plan 08
        SUMMARY for the wire shape. Always returns a contract dict (200);
        VM100 endpoint never 500s on upstream failure (it degrades to a
        _demo=True card + degraded_reason instead).
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as client:
        r = await client.get(
            f"{VM100_BASE_URL}/api/mission-control/surfaced-lesson",
            params={"account_id": account_id, "date": date},
            headers={"Authorization": f"Bearer {VM100_INTERNAL_TOKEN}"},
        )
        r.raise_for_status()
        return r.json()
