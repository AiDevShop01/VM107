"""ForecastSection — Phase 94 §K.

Consensus + dispersion + horizon for major indicators. Driven by external
forecast feed (refreshed daily). Surfaces IntelligenceCard when stale > 30d.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection


class ForecastEntry(BaseModel):
    """A single forecast row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    indicator_id: str = Field(min_length=1)
    horizon: str = Field(
        min_length=1,
        description="Horizon label (e.g., 'Q4-2026', '12m').",
    )
    consensus: float
    dispersion: float = Field(
        ge=0.0,
        description="Std-dev / IQR of forecaster spread.",
    )
    n_forecasters: int = Field(ge=1)
    as_of: datetime


class ForecastSection(BaseSection):
    """Forecast feed section."""

    entries: list[ForecastEntry]
