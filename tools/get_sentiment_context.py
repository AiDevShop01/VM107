"""get_sentiment_context — Tier-3 STUB tool (Wave 8 unbuilt).

Phase 47.2 Tier-3 stub. Returns the locked NotAvailableResponse payload
so Phase 47.3 Decision Framework V1 can read `impact_on_decision: LOW`
and apply only a minor confidence adjustment. NEVER fabricate values
(Architectural Principle #3).

Idempotent + stateless — pure constant return, zero side effects, zero
LLM calls, zero IO. Stubs are NOT lazy — they always return immediately.

When the Wave 8 sentiment service ships, replace `_STUB.model_dump()`
with a real sentiment call (retail_positioning, options_skew,
social_sentiment).
"""
from __future__ import annotations

from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.base import BaseContract, ContractMeta
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetSentimentContextRequest(BaseContract):
    """Request shape — only `trade_id` is required (CONTEXT.md lock)."""

    __meta__ = ContractMeta(vm="vm107-local", endpoint="stub")
    trade_id: str


class GetSentimentContext(ContractTool):
    """LLM-callable: get_sentiment_context(trade_id) -> NotAvailableResponse."""

    _STUB = NotAvailableResponse(
        planned_phase="Wave 8",
        tool="get_sentiment_context",
        would_provide=["retail_positioning", "options_skew", "social_sentiment"],
        impact_on_decision="LOW",
        unblocks_when=["Wave 8 sentiment service shipped"],
    )

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetSentimentContextRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetSentimentContextRequest) -> dict:
        return self._STUB.model_dump()

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return NotAvailableResponse(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
