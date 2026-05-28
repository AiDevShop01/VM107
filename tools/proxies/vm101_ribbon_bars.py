"""Phase 70.5 Decision 18 — proxy for vm101_ribbon_bars.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM101's ribbon bars endpoint, returns a typed ToolPayload, and lets
the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM101 ribbon bars endpoint exists (Phase 65).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm101_client import VM101Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm101RibbonBarsPayload(BaseModel):
    """Typed payload for vm101_ribbon_bars proxy.

    Per-symbol fail-soft: unknown or no-data symbols return available=False
    with empty bars list — never a 4xx/5xx.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    symbol: str
    available: bool = True
    bars: list[float] = Field(default_factory=list)  # last-N closes
    timeframe: str = "M15"
    n: int = 24
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    symbol: str = "EURUSD",
    n: int = 24,
    timeframe: str = "M15",
    **kwargs,
) -> Vm101RibbonBarsPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        symbol: Ribbon symbol (e.g. SPX, NDX, BTC, EURUSD).
        n: Number of bars to fetch. Clamped to [1, 240] server-side.
        timeframe: OHLC timeframe. Default M15.
    """
    client = VM101Client()  # raises RuntimeError if VM101_API_URL unset

    response = await client.get(
        "api/v1/bars",
        params={"symbol": symbol, "n": n, "timeframe": timeframe},
    )

    available = response.get("available", True) if isinstance(response, dict) else True
    bars = response.get("bars", []) if isinstance(response, dict) else []

    return Vm101RibbonBarsPayload(
        symbol=symbol,
        available=available,
        bars=bars,
        timeframe=timeframe,
        n=n,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if available else "none",
                freshness_observed_seconds=60,
                missing_fields=() if available else ("bars",),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "Per-symbol fail-soft: unavailable symbols return available=False",
                "Symbol mapping: SPX→SPX500, NDX→NAS100, BTC→BTCUSD",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM101 bars endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="Symbol has no OHLC data — available=False with empty bars list",
                ),
            ),
        ),
    )
