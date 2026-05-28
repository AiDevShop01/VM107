"""Phase 70.5 Decision 18 — proxy for vm100.analytics_calendar.

VM107 is the canonical epistemic authority boundary. This proxy makes a typed
HTTP call to VM100's analytics calendar endpoint, returns a typed ToolPayload,
and lets the VM107 dispatcher wrap it into a ToolResultEnvelope.

Remote VM returns the payload data; VM107 owns confidence / freshness /
registry_snapshot_hash / citations.

Status: real — VM100 analytics_calendar endpoint exists (Phase 66).
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm100_client import VM100Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class EconomicEventItem(BaseModel):
    """Single economic event from the VM100 analytics calendar."""

    model_config = ConfigDict(extra="allow")

    event_id: str | int | None = None
    title: str | None = None
    currency: str | None = None
    impact: str | None = None
    scheduled_at: datetime | str | None = None
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None


class Vm100AnalyticsCalendarPayload(BaseModel):
    """Typed payload for vm100.analytics_calendar proxy."""

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    events: list[EconomicEventItem] = Field(default_factory=list)
    top_event: EconomicEventItem | None = None
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    method: str = "get_next_24h_events",
    impact: str = "HIGH,MEDIUM",
    **kwargs,
) -> Vm100AnalyticsCalendarPayload:
    """Proxy invocation — env-driven URL, no fallback.

    The fingpt_core/clients/vm100_client.py reads VM100_API_URL at construction
    and raises if missing. NO os.getenv("VM100_API_URL", "default") allowed.

    Args:
        method: Which method to call — "get_next_24h_events" or "get_top_event".
        impact: Comma-separated impact filter (HIGH, MEDIUM, LOW).
    """
    client = VM100Client()  # raises RuntimeError if VM100_API_URL unset

    events: list[EconomicEventItem] = []
    top_event: EconomicEventItem | None = None

    if method == "get_top_event":
        response = await client.get(
            "api/v1/analytics/calendar/top-event",
            params={"impact": impact},
        )
        if response:
            top_event = EconomicEventItem(**response) if isinstance(response, dict) else None
    else:
        response = await client.get(
            "api/v1/analytics/calendar/next-24h",
            params={"impact": impact},
        )
        raw_events = response if isinstance(response, list) else response.get("events", [])
        events = [EconomicEventItem(**e) for e in raw_events if isinstance(e, dict)]

    return Vm100AnalyticsCalendarPayload(
        events=events,
        top_event=top_event,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=120,
                missing_fields=(),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=("VM100 analytics_calendar endpoint reflects current DB state",),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM100 analytics_calendar endpoint timed out",
                ),
                FailureMode(
                    code=FailureModeCode.NO_MATCH_FOUND,
                    detail="No events found in requested window or impact filter",
                ),
            ),
        ),
    )
