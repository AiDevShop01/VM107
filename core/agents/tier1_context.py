"""Phase 47.2 Tier-1 system context builder.

Deterministic, zero-latency curated context built server-side BEFORE
the Coordinator LLM enters tool dispatch. Replaces the Wave 1 inline
context payload (trader pasted instrument/timeframe/strategy_id) with
authoritative fetch from VM100/Postgres/Mongo.

CONTEXT.md lock — payload shape:
  {
    trade_id, instrument, direction, strategy_id,
    last_evaluation (optional summary),
    journal_metadata { timeframe, checklist_snapshot_text, entry, SL, TP }
  }

Per-section graceful degradation: if one underlying source fails, return
partial dict with that section as None. NEVER raise on the chat path.

Tier-1 is a deterministic floor — NOT a tool call. Runs server-side
inside chat.py:process() before _call_coordinator_monologue, so the
context arrives in the FIRST user message the LLM sees with zero LLM
round-trip cost. Tier-2 tools (Plan 04) handle on-demand data fetches.
"""
from __future__ import annotations

import logging
from typing import Any

from fingpt_core.clients import RetryProfile, VM100Client

logger = logging.getLogger(__name__)


_EMPTY_TIER1: dict[str, Any] = {
    "trade_id": None,
    "instrument": None,
    "direction": None,
    "strategy_id": None,
    "last_evaluation": None,
    "journal_metadata": {},
}


async def build_tier1_context(journal_id: str) -> dict[str, Any]:
    """Build curated Tier-1 context for the Coordinator chat path.

    Args:
        journal_id: TradeJournal UUID.

    Returns:
        Curated dict per CONTEXT.md lock. Always includes top-level keys
        (with None values where data is unavailable).
    """
    client = VM100Client(profile=RetryProfile.FAST_FAIL)

    # Section 1: journal + trade lookup (LOAD-BEARING — if this fails,
    # return a minimal stub so the chat path continues with empty context
    # rather than failing the entire turn).
    journal: dict | None = None
    trade: dict | None = None
    try:
        journal = await client.get_journal(journal_id)
        trade_id = (journal or {}).get("trade_id") or journal_id
        trade = await client.get_trade(trade_id)
    except Exception as exc:
        logger.warning(
            "tier1_context: journal/trade fetch failed for journal_id=%s — "
            "returning minimal stub: %s",
            journal_id, exc,
        )
        return dict(_EMPTY_TIER1)

    # Section 2: last evaluation (graceful — None on any failure).
    last_eval: dict | None = None
    try:
        eval_record = await client.get_current_evaluation(journal_id)
        if eval_record:
            last_eval = {
                "evaluation_id": eval_record.get("evaluation_id"),
                "recommendation": eval_record.get("recommendation"),
                "score": eval_record.get("score"),
                "confidence": eval_record.get("confidence"),
                "created_at": eval_record.get("created_at"),
            }
    except Exception as exc:
        logger.debug(
            "tier1_context: last evaluation fetch failed (graceful) for "
            "journal_id=%s: %s",
            journal_id, exc,
        )
        last_eval = None

    return {
        "trade_id": trade.get("id") or journal.get("trade_id"),
        "instrument": trade.get("instrument"),
        "direction": trade.get("direction"),
        "strategy_id": trade.get("strategy_id"),
        "last_evaluation": last_eval,
        "journal_metadata": {
            "timeframe": trade.get("timeframe"),
            "checklist_snapshot_text": journal.get("checklist_snapshot_text"),
            "entry_price": trade.get("entry_price"),
            "stop_loss_price": trade.get("stop_loss_price"),
            "take_profit_price": trade.get("take_profit_price"),
        },
    }
