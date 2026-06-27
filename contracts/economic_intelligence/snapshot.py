"""EconomicSnapshot — Phase 94 aggregate.

Composite of 14 sections + SnapshotHealth. Persisted forever per §A.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base_section import BaseSection


class SnapshotHealth(BaseModel):
    """Composite health metric for the whole snapshot.

    Distinct from per-section SectionStatus — represents the aggregate
    readiness of the entire situation room (§D).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1 composite readiness score.",
    )
    sections_ready: int = Field(ge=0)
    sections_total: int = Field(ge=0)
    stale_sections: list[str] = Field(
        description="section_ids that are LAST_KNOWN_GOOD / DEGRADED.",
    )


class EconomicSnapshot(BaseModel):
    """Aggregate of all 14 sections for a single (country, generated_at).

    Persisted forever to enable replay (§A). data_version is a Postgres
    autoincrement; schema_version is the wire-format version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(min_length=1)
    country: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 (uppercase).",
    )
    generated_at: datetime
    sections: dict[str, BaseSection] = Field(
        description=(
            "section_id -> section envelope. May be empty during initial "
            "warming, in which case snapshot_health.score == 0."
        ),
    )
    snapshot_health: SnapshotHealth
    regime: str = Field(
        min_length=1,
        description="Active macro regime (e.g., 'late_cycle', 'stagflation').",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    schema_version: str = Field(default="1", min_length=1)
    data_version: int = Field(
        ge=1,
        description="Monotonic per-(country) version. Postgres autoinc.",
    )

    @field_validator("country")
    @classmethod
    def _country_must_be_uppercase_alpha(cls, v: str) -> str:
        if len(v) != 2 or not v.isalpha() or v != v.upper():
            raise ValueError(
                "country must be ISO 3166-1 alpha-2, uppercase (e.g., 'US')."
            )
        return v
