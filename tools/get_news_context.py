"""get_news_context — Tier-3 STUB tool (Phase 31 unbuilt).

Phase 47.2 Tier-3 stub. Returns the locked NotAvailableResponse payload
so Phase 47.3 Decision Framework V1 can read `impact_on_decision: HIGH`
and reduce confidence appropriately. NEVER fabricate values
(Architectural Principle #3).

Idempotent + stateless — pure constant return, zero side effects, zero
LLM calls, zero IO. Stubs are NOT lazy — they always return immediately.

When Phase 31 ships, replace `_STUB.model_dump()` with a real news
pipeline call (scheduled_events, breaking_headlines, event_proximity).
"""
from __future__ import annotations

from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.base import BaseContract, ContractMeta
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetNewsContextRequest(BaseContract):
    """Request shape — only `trade_id` is required (CONTEXT.md lock)."""

    __meta__ = ContractMeta(vm="vm107-local", endpoint="stub")
    trade_id: str


class GetNewsContext(ContractTool):
    """LLM-callable: get_news_context(trade_id) -> NotAvailableResponse."""

    _STUB = NotAvailableResponse(
        planned_phase="Phase 31",
        tool="get_news_context",
        would_provide=["scheduled_events", "breaking_headlines", "event_proximity"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 31 complete", "News pipeline active"],
    )

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetNewsContextRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetNewsContextRequest) -> dict:
        return self._STUB.model_dump()

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return NotAvailableResponse(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
