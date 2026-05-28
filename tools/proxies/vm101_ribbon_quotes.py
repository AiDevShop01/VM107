"""Phase 70.5 Decision 18 — proxy for vm101_ribbon_quotes.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM101's ribbon quotes endpoint, returns a typed ToolPayload, and
lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM101 ribbon quotes endpoint exists (Phase 65).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm101_client import VM101Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class RibbonQuoteTile(BaseModel):
    """Single ribbon quote tile."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    available: bool = True
    price: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    reason: str | None = None  # populated when available=False
    _demo: bool = False


class Vm101RibbonQuotesPayload(BaseModel):
    """Typed payload for vm101_ribbon_quotes proxy.

    Per-symbol fail-soft: unknown or unavailable symbols return available=False
    with diagnostic reason — never a 4xx/5xx.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    tiles: list[RibbonQuoteTile] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    symbols: list[str] | None = None,
    **kwargs,
) -> Vm101RibbonQuotesPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        symbols: List of ribbon symbols (e.g. ["SPX", "NDX", "BTC"]).
                 Defaults to standard ribbon set if not specified.
    """
    client = VM101Client()  # raises RuntimeError if VM101_API_URL unset

    _symbols = symbols or ["SPX", "NDX", "BTC", "VIX", "DXY", "US10Y"]

    params: dict = {"symbols": ",".join(_symbols)}
    response = await client.get("api/v1/quotes", params=params)

    raw_tiles = response if isinstance(response, list) else response.get("tiles", [])
    tiles = [RibbonQuoteTile(**t) for t in raw_tiles if isinstance(t, dict)]

    all_available = all(t.available for t in tiles)

    return Vm101RibbonQuotesPayload(
        tiles=tiles,
        symbols=_symbols,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if all_available else "partial",
                freshness_observed_seconds=30,
                missing_fields=() if all_available else tuple(
                    t.symbol for t in tiles if not t.available
                ),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "Per-symbol fail-soft: unavailable symbols return available=False",
                "VM100 maps available=False tiles to _demo=True on RibbonTile contract",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM101 quotes endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.PARTIAL_DATA,
                    detail="Some ribbon symbols unavailable — partial quote data returned",
                ),
            ),
        ),
    )
