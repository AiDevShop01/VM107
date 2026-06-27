"""BaseSection — common envelope for every Phase 94 section.

Per CONTEXT.md §D: every section carries the same envelope so the frontend
can render generically and the snapshot coordinator can incrementally
regenerate. Specialised sections inherit and add typed payload fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .provenance import ProvenanceObject


class SectionStatus(str, Enum):
    """6-state degradation enum per §D.

    READY            — fresh, fully populated.
    LAST_KNOWN_GOOD  — stale but valid; UI shows freshness chip.
    UPDATING         — recompute in flight; UI shows shimmer over LKG payload.
    DEGRADED         — partial data; some sub-fields missing.
    UNAVAILABLE      — no payload; IntelligenceCard with reason/ETA.
    ERROR            — explicit failure; render-walk reports.
    """

    READY = "READY"
    LAST_KNOWN_GOOD = "LAST_KNOWN_GOOD"
    UPDATING = "UPDATING"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class BaseSection(BaseModel):
    """Common envelope for every section in an EconomicSnapshot.

    Frozen + extra='forbid'. schema_version defaults to "1" (monotonic-int
    versioning — bumped only when the wire format changes).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str = Field(
        min_length=1,
        description="Canonical section identifier (e.g., 'pillars', 'themes').",
    )
    schema_version: str = Field(
        default="1",
        min_length=1,
        description="Wire-format version. Monotonic integer-as-string.",
    )
    version: int = Field(
        ge=1,
        description="Per-section monotonic version. Bumped on every regen.",
    )
    generated_at: datetime = Field(
        description="UTC timestamp when this section was generated.",
    )
    snapshot_id: str = Field(
        min_length=1,
        description="EconomicSnapshot.snapshot_id this section belongs to.",
    )
    freshness_seconds: int = Field(
        ge=0,
        description="Age of the underlying data in seconds.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Section-level confidence in [0,1].",
    )
    status: SectionStatus = Field(
        description="Per-section PIRF degradation state.",
    )
    agent: str = Field(
        min_length=1,
        description=(
            "Producing agent or service ID "
            "(e.g., 'vm107.executive_summary', 'vm102.pillar_engine')."
        ),
    )
    execution_time_ms: int = Field(
        ge=0,
        description="Wall-clock execution time for this section, ms.",
    )
    citations: list[str] = Field(
        description="Citation grammar refs (e.g., 'ref:indicator:CPIAUCSL').",
    )
    limitations: list[str] = Field(
        description="Human-readable caveats (empty list if none).",
    )
    depends_on: list[str] = Field(
        description="Upstream section_ids / event_types this depends on.",
    )
    provenance: ProvenanceObject = Field(
        description="Provenance metadata (§F.7).",
    )
