"""Phase 47.2 Tier-1 system context builder.

Deterministic, zero-latency curated context built server-side BEFORE
the Coordinator LLM enters tool dispatch. Replaces the Wave 1 inline
context payload (trader pasted instrument/timeframe/strategy_id) with
authoritative fetch from VM100.

CONTEXT.md lock — payload shape:
  {
    trade_id, instrument, direction, strategy_id,
    last_evaluation (optional summary),
    journal_metadata { timeframe, entry_price, stop_loss_price, take_profit_price, ... }
  }

Per-section graceful degradation: if the VM100 fetch fails, return a
minimal stub (all top-level keys present with None) so the chat path
continues with empty context rather than failing the entire turn.

Tier-1 is a deterministic floor — NOT a tool call. Runs server-side
inside chat.py:process() before _call_coordinator_monologue, so the
context arrives in the FIRST user message the LLM sees with zero LLM
round-trip cost. Tier-2 tools (Plan 04) handle on-demand data fetches.

Implementation note: this module deliberately uses stdlib httpx instead
of fingpt_core.clients.VM100Client because VM107's runtime container
does NOT install fingpt_core. The internal endpoint
GET /api/journal/internal/journal/{id}/tier1-context returns the
curated bundle in one JOIN — no auth (docker network only).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


_EMPTY_TIER1: dict[str, Any] = {
    "trade_id": None,
    "instrument": None,
    "direction": None,
    "strategy_id": None,
    "last_evaluation": None,
    "journal_metadata": {},
}


def _vm100_internal_base_url() -> str:
    """Resolve VM100 internal base URL from required VM100_API_URL env var."""
    return os.environ["VM100_API_URL"]


async def build_tier1_context(journal_id: str) -> dict[str, Any]:
    """Build curated Tier-1 context for the Coordinator chat path.

    Args:
        journal_id: TradeJournal UUID.

    Returns:
        Curated dict per CONTEXT.md lock. Always includes top-level keys
        (with None values where data is unavailable).
    """
    url = (
        f"{_vm100_internal_base_url().rstrip('/')}"
        f"/api/journal/internal/journal/{journal_id}/tier1-context"
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = await client.get(url)
        if response.status_code == 404:
            logger.info(
                "tier1_context: VM100 reports journal not found for journal_id=%s — "
                "returning empty stub",
                journal_id,
            )
            return dict(_EMPTY_TIER1)
        response.raise_for_status()
        bundle = response.json()
    except Exception as exc:
        logger.warning(
            "tier1_context: VM100 fetch failed for journal_id=%s — "
            "returning minimal stub: %s",
            journal_id,
            exc,
        )
        return dict(_EMPTY_TIER1)

    # Server already returns the curated shape. Defensive merge against
    # the empty stub so missing keys never raise downstream.
    merged = dict(_EMPTY_TIER1)
    merged.update(
        {
            "trade_id": bundle.get("trade_id"),
            "instrument": bundle.get("instrument"),
            "direction": bundle.get("direction"),
            "strategy_id": bundle.get("strategy_id"),
            "last_evaluation": bundle.get("last_evaluation"),
            "journal_metadata": bundle.get("journal_metadata") or {},
        }
    )
    return merged
