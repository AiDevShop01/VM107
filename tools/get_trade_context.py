"""get_trade_context — fetch curated trade journal data via VM100 API.

Phase 47.2 Tier-2 real tool. Idempotent + stateless (CONTEXT lock).

Returns the canonical journal payload for a single trade — instrument,
direction, strategy_id, entry/SL/TP, notes, timeframe, checklist snapshot,
and (when available) the last formal evaluation summary.

VM100Client has no `get_trade(trade_id)` method (Phase 39 client surface
only ships `get_recent_trades` and `create_pre_trade_entry`); we therefore
go through the generic BaseVMClient `.get(path)` against the existing
`GET /api/v1/trades/{trade_id}` route from VM100/backend/api/trading_router.py.
"""
from __future__ import annotations

from typing import Any

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.agents.trade_context import (
    GetTradeContextRequest,
    GetTradeContextResponse,
)
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetTradeContext(ContractTool):
    """LLM-callable: get_trade_context(trade_id)."""

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetTradeContextRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetTradeContextRequest) -> dict:
        client = VM100Client(profile=RetryProfile.FAST_FAIL)
        trade: dict[str, Any] = {}
        try:
            if hasattr(client, "get_trade"):
                trade = await client.get_trade(request.trade_id)  # type: ignore[attr-defined]
            else:
                trade = await client.get(f"api/v1/trades/{request.trade_id}")
        except Exception:
            # Graceful per-section degradation (CONTEXT.md). DRAFT journals
            # have no executed Trade row; the LLM is sometimes given the
            # journal_id as a stand-in for trade_id. Return the request
            # surface with empty/None fields rather than raising — the
            # LLM still gets a usable response shape and Tier-1 has the
            # high-level metadata.
            trade = {}

        return {
            "trade_id": request.trade_id,
            "instrument": trade.get("instrument"),
            "direction": trade.get("direction"),
            "strategy_id": trade.get("strategy_id"),
            "entry_price": trade.get("entry_price"),
            "stop_loss_price": trade.get("stop_loss_price"),
            "take_profit_price": trade.get("take_profit_price"),
            "notes": trade.get("notes"),
            "timeframe": trade.get("timeframe"),
            "checklist_snapshot_text": trade.get("checklist_snapshot_text"),
            # Plan 07 Tier-1 builder owns evaluation summary fetch — do not
            # populate it here (CONTEXT.md OQ-1 / OQ-2 + plan-body NOTE).
            "last_evaluation": None,
        }

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return GetTradeContextResponse(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
