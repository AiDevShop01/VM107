"""Phase 70.5 Decision 18 — proxy for vm102.structural_events.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM102's structural events endpoint, returns a typed ToolPayload,
and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Status: real — VM102 structural events endpoint exists (Phase 65).
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm102_client import VM102Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class StructuralEventItem(BaseModel):
    """Single FVG lifecycle event from VM102."""

    model_config = ConfigDict(extra="allow")

    event_id: str | int | None = None
    symbol: str | None = None
    timeframe: str | None = None
    event_type: str | None = None  # CREATED / TOUCHED / FILLED / INVALIDATED
    price_low: float | None = None
    price_high: float | None = None
    occurred_at: datetime | str | None = None


class Vm102StructuralEventsPayload(BaseModel):
    """Typed payload for vm102.structural_events proxy.

    Per-VM-boundary fail-soft: empty result is HTTP 200 with events=[], _demo=True.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    symbols: list[str] = Field(default_factory=list)
    timeframe: str = "H1"
    events: list[StructuralEventItem] = Field(default_factory=list)
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    symbols: list[str] | None = None,
    timeframe: str = "H1",
    event_types: list[str] | None = None,
    **kwargs,
) -> Vm102StructuralEventsPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Args:
        symbols: One or more instrument symbols. Defaults to ["EURUSD"].
        timeframe: OHLC timeframe. Default H1.
        event_types: FVG event types to filter. Only "fvg" supported now;
                     "sweep", "bos", "choch" return HTTP 400 with future list.
    """
    client = VM102Client()  # raises RuntimeError if VM102_API_URL unset

    _symbols = symbols or ["EURUSD"]
    params: dict = {
        "symbols": ",".join(_symbols),
        "timeframe": timeframe,
    }
    if event_types:
        params["event_types"] = ",".join(event_types)

    response = await client.get("api/v1/structural-events", params=params)

    raw_events = response.get("events", []) if isinstance(response, dict) else []
    events = [StructuralEventItem(**e) for e in raw_events if isinstance(e, dict)]
    demo = response.get("_demo", False) if isinstance(response, dict) else False

    return Vm102StructuralEventsPayload(
        symbols=_symbols,
        timeframe=timeframe,
        events=events,
        _demo=demo,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete" if events else "none",
                freshness_observed_seconds=120,
                missing_fields=() if events else ("events",),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "Operational boundary: VM102 does NOT expose user/account context here",
                "Per-VM-boundary fail-soft: empty result is 200 with _demo=True",
                "FVG lifecycle events only — sweep/bos/choch reserved for future plans",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM102 structural-events endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No structural events found for requested symbols/timeframe — empty list with _demo=True",
                ),
            ),
        ),
    )
