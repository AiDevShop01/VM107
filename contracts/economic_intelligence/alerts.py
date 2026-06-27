"""AlertsSection — Phase 94 §O.

Active alerts for the situation room. Each alert has severity, label,
deep-link to the triggering event/indicator.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection
from .events import EventSeverity


class Alert(BaseModel):
    """A single active alert."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    alert_id: str = Field(min_length=1)
    raised_at: datetime
    severity: EventSeverity
    label: str = Field(min_length=1)
    deep_link: str = Field(min_length=1)
    citations: list[str]


class AlertsSection(BaseSection):
    """Active alerts section."""

    alerts: list[Alert]
