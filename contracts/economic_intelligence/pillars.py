"""PillarsSection — Phase 94 §F deterministic pillar engine output.

Four canonical pillars (Growth/Inflation/Liquidity/RiskAppetite), each with
a level, momentum vector, breadth, confidence, state, sparkline_90d, and
provenance.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base_section import BaseSection, SectionStatus
from .provenance import ProvenanceObject


class PillarState(str, Enum):
    """6-state pillar lifecycle per §F."""

    STRONG_POSITIVE = "STRONG_POSITIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    STRONG_NEGATIVE = "STRONG_NEGATIVE"
    UNCERTAIN = "UNCERTAIN"


PillarName = Literal["Growth", "Inflation", "Liquidity", "RiskAppetite"]


class Pillar(BaseModel):
    """A single pillar (one of Growth/Inflation/Liquidity/RiskAppetite)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: PillarName
    level: float = Field(ge=0.0, le=100.0)
    momentum: dict[str, float] = Field(
        description="Momentum vector with keys {'1m', '3m', '12m'}.",
    )
    breadth: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    contributors: list[str] = Field(
        description="Indicator IDs that fed into this pillar.",
    )
    state: PillarState
    sparkline_90d: list[float] = Field(
        description="90 daily level values for inline sparkline.",
    )
    provenance: ProvenanceObject

    @model_validator(mode="after")
    def _momentum_keys(self) -> "Pillar":
        if set(self.momentum.keys()) != {"1m", "3m", "12m"}:
            raise ValueError("momentum must have exactly the keys {'1m', '3m', '12m'}.")
        return self


class PillarsSection(BaseSection):
    """Section payload carrying the 4 canonical pillars."""

    pillars: list[Pillar] = Field(
        description="Ordered list of pillars (typically 4: G/I/L/R).",
    )

    @model_validator(mode="after")
    def _ready_requires_non_empty_contributors(self) -> "PillarsSection":
        if self.status is SectionStatus.READY:
            for pillar in self.pillars:
                if not pillar.contributors:
                    raise ValueError(
                        "READY PillarsSection requires non-empty "
                        f"contributors for every pillar (offender: {pillar.name})."
                    )
        return self
