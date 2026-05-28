"""Phase 70.5 Decision 18 — proxy for vm102.regime_current.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM102's current regime endpoint, returns a typed ToolPayload, and
lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM102 /api/v1/regime/current endpoint exists (Phase 65).
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class Vm102RegimeCurrentPayload(BaseModel):
    """Typed payload for vm102.regime_current proxy.

    Maps down from VM102's RegimeSummaryContract — analytical fields stripped
    at the boundary per VM102 bounded-context lock.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    symbol: str
    timeframe: str
    label: str | None = None
    regime_type: str | None = None  # open string; composite regimes supported
    structure: str | None = None
    confidence: float | None = None
    bias: str | None = None  # "bullish" | "bearish" | "neutral"
    updated_at: datetime | str | None = None
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    symbol: str = "EURUSD",
    timeframe: str = "H1",
    **kwargs,
) -> Vm102RegimeCurrentPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        symbol: Single instrument symbol (e.g. EURUSD).
        timeframe: One of M1/M5/M15/M30/H1/H4/D1.
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    try:
        response = await client.get(
            "api/v1/regime/current",
            params={"symbol": symbol, "timeframe": timeframe},
        )
    except Exception:
        # 404 or unavailable — return DEMO shape per VM102 spec
        return Vm102RegimeCurrentPayload(
            symbol=symbol,
            timeframe=timeframe,
            label="—",
            bias="neutral",
            _demo=True,
            provenance=ToolProvenance(
                signals=ToolConfidenceSignals(
                    evidence_quality="none",
                    freshness_observed_seconds=None,
                    missing_fields=("regime_type", "structure", "confidence"),
                    is_deterministic=True,
                ),
                declared_failure_modes=(
                    FailureMode(
                        code=FailureModeCode.NO_MATCH_FOUND,
                        detail=f"No RegimeDetection row for {symbol}x{timeframe}",
                    ),
                ),
            ),
        )

    return Vm102RegimeCurrentPayload(
        symbol=symbol,
        timeframe=timeframe,
        label=response.get("label"),
        regime_type=response.get("regime_type"),
        structure=response.get("structure"),
        confidence=response.get("confidence"),
        bias=response.get("bias"),
        updated_at=response.get("updated_at"),
        _demo=response.get("_demo", False),
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=120,
                missing_fields=(),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "RegimeSummaryContract: analytical fields stripped at VM102 boundary",
                "regime_type is open string — composite values like 'COMPRESSION → EXPANSION' are valid",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 regime/current endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail=f"No RegimeDetection row for {symbol}x{timeframe} — returns DEMO shape",
                ),
            ),
        ),
    )
