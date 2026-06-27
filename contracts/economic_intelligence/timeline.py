"""TimelineSection — Phase 94 §I.

Chronological feed of recent EconomicEvents projected into the situation
room. Each entry carries label, severity, and a deep-link target.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection
from .events import EventSeverity


class TimelineEntry(BaseModel):
    """A single timeline entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    occurred_at: datetime
    label: str = Field(min_length=1)
    severity: EventSeverity
    deep_link: str = Field(
        min_length=1,
        description="Onward route (e.g., '/markets/macro/event/<id>').",
    )


class TimelineSection(BaseSection):
    """Section payload for the chronological event timeline."""

    entries: list[TimelineEntry]
