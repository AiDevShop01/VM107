"""get_regime_context — Tier-3 STUB tool (Phase 34 unbuilt).

Phase 47.2 Tier-3 stub. Returns the locked NotAvailableResponse payload
so Phase 47.3 Decision Framework V1 can read `impact_on_decision: MEDIUM`
and adjust confidence accordingly. NEVER fabricate values
(Architectural Principle #3).

Idempotent + stateless — pure constant return, zero side effects, zero
LLM calls, zero IO. Stubs are NOT lazy — they always return immediately.

When Phase 34 ships, replace `_STUB.model_dump()` with a real regime
classifier call (trend_regime, volatility_regime, correlation_regime).
"""
from __future__ import annotations

from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.base import BaseContract, ContractMeta
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetRegimeContextRequest(BaseContract):
    """Request shape — only `trade_id` is required (CONTEXT.md lock)."""

    __meta__ = ContractMeta(vm="vm107-local", endpoint="stub")
    trade_id: str


class GetRegimeContext(ContractTool):
    """LLM-callable: get_regime_context(trade_id) -> NotAvailableResponse."""

    _STUB = NotAvailableResponse(
        planned_phase="Phase 34",
        tool="get_regime_context",
        would_provide=["trend_regime", "volatility_regime", "correlation_regime"],
        impact_on_decision="MEDIUM",
        unblocks_when=["Phase 34 complete"],
    )

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetRegimeContextRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetRegimeContextRequest) -> dict:
        return self._STUB.model_dump()

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return NotAvailableResponse(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
