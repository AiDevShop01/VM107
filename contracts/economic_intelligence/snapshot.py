"""EconomicSnapshot — Phase 94 aggregate.

Composite of 14 sections + SnapshotHealth. Persisted forever per §A.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    # Sections are stored as raw dicts (not validated against BaseSection at
    # round-trip time) so typed subclasses like Phase 95 Plan 11's `Domain`
    # — which add `primary_pillars`, `primary_analyst`, `related_domains`,
    # `health_score`, `current_state`, `risk_level`, `drivers`,
    # `constraints`, `tailwinds`, `headwinds`, `latest_releases`, `headline`,
    # `next_review_at`, `key_question`, `evidence_refs` on top of the
    # BaseSection envelope — survive a JSON round trip through
    # `model_validate_json`. Phase 94's original `dict[str, BaseSection]`
    # annotation triggered `extra='forbid'` rejection on every typed
    # subclass because Pydantic instantiated the parent class. Resolvers
    # already coerce via `.model_dump(mode='json')` (BaseSection-derived)
    # or `dict(section)` (plain dict) — see `_section_dict` in each
    # section_resolver module.
    sections: dict[str, Any] = Field(
        description=(
            "section_id -> section envelope dict. May be empty during initial "
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
