"""get_liquidity_context — typed VM102 read of ACTIVE liquidity zones.

Phase 47.2.1: NO Polars, NO filesystem reads, NO _resolve_instrument hop.
Pure transport: validates request -> calls VM102 -> validates response.

LLM-callable: get_liquidity_context(instrument, timeframe, lookback_bars?).

Architecture (Phase 47.2.1 lock):
  * Tools take `instrument` directly from Tier-1 context (CONTEXT.md §5);
    the VM107->VM100 resolve hop is gone.
  * "Active-only" filtering is computed server-side by VM102 (Phase 28
    left-anti join against the events stream — see Plan 04 for details).
  * On transport failure (httpx.ConnectError / TimeoutException / 5xx),
    the tool synthesizes a `not_available` envelope rather than raising
    so the LLM never sees a transport exception (CONTEXT.md §2 trigger #1).
  * lookback_bars > 500 is silently clamped to 500 BEFORE Pydantic
    validation (defense in depth — VM102 also enforces 422; CONTEXT.md §3,
    OQ-6).
  * Plan 02's `@model_validator` on the response envelope catches malformed
    VM102 payloads at the boundary (OQ-8).
"""
from __future__ import annotations

import httpx

from fingpt_core.clients import RetryProfile, VM102Client
from fingpt_core.contracts.agents.liquidity_context import (
    GetLiquidityContextRequest,
    GetLiquidityContextResponse,
)
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


LOOKBACK_HARD_CAP = 500  # CONTEXT.md §3 lock


class GetLiquidityContext(ContractTool):
    """LLM-callable typed read of active liquidity zones."""

    def _validate_request(self, args: dict) -> GetLiquidityContextRequest:
        # Defense in depth — silent clamp BEFORE Pydantic le=500 fires.
        # The LLM should never see HTTP 422 from a misbehaving lookback;
        # it would just retry with the same value (CONTEXT.md §3, OQ-6).
        if "lookback_bars" in args and isinstance(
            args["lookback_bars"], (int, float)
        ):
            if args["lookback_bars"] > LOOKBACK_HARD_CAP:
                args = {**args, "lookback_bars": LOOKBACK_HARD_CAP}

        try:
            return GetLiquidityContextRequest(**args)
        except Exception as e:  # noqa: BLE001
            # extra=forbid will reject legacy `trade_id` here (Critical Finding 4)
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: GetLiquidityContextRequest) -> dict:
        client = VM102Client(profile=RetryProfile.FAST_FAIL)
        try:
            return await client.get_liquidity(
                instrument=request.instrument,
                timeframe=request.timeframe,
                lookback_bars=request.lookback_bars,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            # VM102 unreachable → honest not_available (CONTEXT.md §2 trigger #1)
            return self._synthesize_not_available(
                request, message=str(e), reason_kind="transport",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                return self._synthesize_not_available(
                    request, message=str(e), reason_kind="server_error",
                )
            # 4xx other than 422-misuse: still bubble up — caller must fix args
            raise
        finally:
            await client.close()

    def _validate_response(self, data: dict) -> GetLiquidityContextResponse:
        try:
            return GetLiquidityContextResponse(**data)
        except Exception as e:  # noqa: BLE001
            # Plan 02 @model_validator catches malformed envelopes from VM102.
            # CONTEXT.md OQ-8 — boundary enforcement.
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    @staticmethod
    def _synthesize_not_available(
        request: GetLiquidityContextRequest,
        message: str,
        reason_kind: str = "transport",
    ) -> dict:
        """Construct an envelope passing the Plan 02 invariant.

        reason_kind:
            "transport"    — httpx.ConnectError / TimeoutException
            "server_error" — VM102 returned 5xx
        """
        return {
            "status": "not_available",
            "data": None,
            "meta": {
                "planned_phase": (
                    "VM102 reachable + liquidity partitions present for "
                    f"{request.instrument} {request.timeframe}"
                ),
                "tool": "get_liquidity_context",
                "would_provide": [
                    "fvg_zones",
                    "equal_highs",
                    "equal_lows",
                    "imbalance_zones",
                ],
                "impact_on_decision": "HIGH",
                "unblocks_when": [
                    "VM102 backend healthy",
                    f"liquidity partitions exist for {request.instrument} {request.timeframe}",
                ],
            },
        }
