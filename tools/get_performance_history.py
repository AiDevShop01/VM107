"""get_performance_history — Tier-3 STUB tool (Phase 47.4 unbuilt).

Phase 47.2 Tier-3 stub. Returns the locked NotAvailableResponse payload
so Phase 47.3 Decision Framework V1 can read `impact_on_decision: MEDIUM`
and adjust confidence accordingly. NEVER fabricate values
(Architectural Principle #3).

Idempotent + stateless — pure constant return, zero side effects, zero
LLM calls, zero IO. Stubs are NOT lazy — they always return immediately.

When Phase 47.4 ships, replace `_STUB.model_dump()` with a real Postgres
trade-evaluation history call (strategy_win_rate, recent_drawdown,
similar_setup_outcomes).
"""
from __future__ import annotations

from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.base import BaseContract, ContractMeta
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetPerformanceHistoryRequest(BaseContract):
    """Request shape — only `trade_id` is required (CONTEXT.md lock)."""

    __meta__ = ContractMeta(vm="vm107-local", endpoint="stub")
    trade_id: str


class GetPerformanceHistory(ContractTool):
    """LLM-callable: get_performance_history(trade_id) -> NotAvailableResponse."""

    _STUB = NotAvailableResponse(
        planned_phase="Phase 47.4",
        tool="get_performance_history",
        would_provide=["strategy_win_rate", "recent_drawdown", "similar_setup_outcomes"],
        impact_on_decision="MEDIUM",
        unblocks_when=[
            "Phase 47.4 complete",
            "Postgres trade-evaluation history populated",
        ],
    )

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetPerformanceHistoryRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetPerformanceHistoryRequest) -> dict:
        return self._STUB.model_dump()

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return NotAvailableResponse(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
