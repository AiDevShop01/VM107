"""EconomicEvent — Phase 94 §B.3 event bus contract.

Eight canonical event types flow through the bus. Each event carries a
typed payload (open dict here; subscribers cast to their own schema) plus
country, severity, occurred_at, source.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    """8 canonical event types per §B.3."""

    MACRO_RELEASE = "macro_release"
    CENTRAL_BANK = "central_bank"
    REGIME_CHANGE = "regime_change"
    DISCOVERY = "discovery"
    FORECAST_UPDATE = "forecast_update"
    RESEARCH = "research"
    ALERT = "alert"
    STRUCTURAL_UPDATE = "structural_update"


class EventSeverity(str, Enum):
    """Severity levels gating downstream regeneration triggers."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EconomicEvent(BaseModel):
    """A single event published to the Phase 94 event bus.

    Subscribers (executive_summary, theme_monitor, etc.) filter on
    event_type + severity + country and dispatch their own regeneration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(
        min_length=1,
        description="Unique event identifier (uuid4 recommended).",
    )
    event_type: EventType
    severity: EventSeverity
    country: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 (uppercase).",
    )
    occurred_at: datetime
    source: str = Field(
        min_length=1,
        description="Producer ID (e.g., 'vm101.economic_event').",
    )
    payload: dict[str, Any] = Field(
        description="Event-type-specific payload (open dict here).",
    )
    # knowledge_time (Phase 168, D-06 event carrier): the as-of the MACRO_RELEASE
    # fan-out should honor. Optional-defaulted so existing publishers keep working;
    # immutable forwarding through the fan-out is closed by 168-04.
    knowledge_time: datetime | None = None
    schema_version: str = Field(default="2", min_length=1)

    @field_validator("country")
    @classmethod
    def _country_must_be_uppercase_alpha(cls, v: str) -> str:
        if len(v) != 2 or not v.isalpha() or v != v.upper():
            raise ValueError(
                "country must be ISO 3166-1 alpha-2, uppercase (e.g., 'US')."
            )
        return v
