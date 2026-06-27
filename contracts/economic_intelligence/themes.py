"""ThemeMonitorSection — Phase 94 §H.

Themes have an 8-state lifecycle and a strength score (0..100). The state
machine is implemented in VM107 theme_engine; this contract is the wire
format.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection


class ThemeState(str, Enum):
    """8-state theme lifecycle per §H.2."""

    CANDIDATE = "Candidate"
    EMERGING = "Emerging"
    STRENGTHENING = "Strengthening"
    DOMINANT = "Dominant"
    STABLE = "Stable"
    WEAKENING = "Weakening"
    DORMANT = "Dormant"
    ARCHIVED = "Archived"


class Theme(BaseModel):
    """A single tracked theme."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    theme_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    strength: float = Field(ge=0.0, le=100.0)
    state: ThemeState
    drivers: list[str] = Field(
        description="Indicator IDs / events driving the theme.",
    )
    first_seen: str = Field(
        min_length=1,
        description="ISO-8601 timestamp when the theme was first observed.",
    )
    last_changed: str = Field(
        min_length=1,
        description="ISO-8601 timestamp of last state transition.",
    )


class ThemeMonitorSection(BaseSection):
    """Section payload for theme monitoring."""

    themes: list[Theme] = Field(
        description="All active themes (excluding ARCHIVED).",
    )
