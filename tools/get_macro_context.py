"""get_macro_context — Tier-3 STUB tool (Phase 33 unbuilt).

Phase 47.2 Tier-3 stub. Returns the locked NotAvailableResponse payload
so Phase 47.3 Decision Framework V1 can read `impact_on_decision: HIGH`
and reduce confidence appropriately. NEVER fabricate values
(Architectural Principle #3).

Idempotent + stateless — pure constant return, zero side effects, zero
LLM calls, zero IO. Stubs are NOT lazy — they always return immediately.

When Phase 33 ships, replace `_STUB.model_dump()` with a real macro
ingestion call (interest_rate_decisions, inflation_data, central_bank_bias).
"""
from __future__ import annotations

from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.base import BaseContract, ContractMeta
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetMacroContextRequest(BaseContract):
    """Request shape — only `trade_id` is required (CONTEXT.md lock)."""

    __meta__ = ContractMeta(vm="vm107-local", endpoint="stub")
    trade_id: str


class GetMacroContext(ContractTool):
    """LLM-callable: get_macro_context(trade_id) -> NotAvailableResponse."""

    _STUB = NotAvailableResponse(
        planned_phase="Phase 33",
        tool="get_macro_context",
        would_provide=["interest_rate_decisions", "inflation_data", "central_bank_bias"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 33 complete", "Macro ingestion pipeline active"],
    )

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetMacroContextRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetMacroContextRequest) -> dict:
        return self._STUB.model_dump()

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return NotAvailableResponse(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
