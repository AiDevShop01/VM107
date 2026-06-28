"""Domain — Phase 95 §C macro Domain section contract.

The Domain is the typed contract for one of the 12 canonical macro domains
(Growth / Inflation / Labour / Housing / Credit / Monetary Policy / Fiscal /
External Sector / Manufacturing / Consumer / Financial Conditions /
Commodities — CONTEXT §A). Each Domain feeds one or more of the four
analytical pillars (CONTEXT §B).

Domain extends BaseSection so it shares the same envelope as every other
Phase 94 section (snapshot_id, version, generated_at, status, provenance, …).
The single source of truth for the canonical 12 lives in
``contracts/economic_intelligence/domain_catalog.yaml`` — frontend route
registry, backend resolver, Capability Registry, and Neo4j seed all read
from that file (Pitfall 5: no hand-list drift).

Frozen + extra='forbid' inherited from BaseSection. Do not relax.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base_section import BaseSection

# Canonical pillar set (CONTEXT §B). Domain.primary_pillars must be a
# non-empty subset of these four.
_VALID_PILLARS = frozenset({"Growth", "Inflation", "Liquidity", "Risk"})


class Driver(BaseModel):
    """A single contributing driver behind a Domain's current_state.

    Drivers explain *why* the domain is in its current state — e.g.,
    "ISM new orders rising" with contribution 0.4, direction 'up'.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Human-readable driver name.")
    contribution: float = Field(
        ge=-1.0,
        le=1.0,
        description="Signed contribution to the domain's health_score in [-1, 1].",
    )
    direction: Literal["up", "down", "flat"] = Field(
        description="Sign of the driver's recent change.",
    )


class IndicatorRef(BaseModel):
    """Reference to one of the top indicators powering a Domain.

    Pure pointer + weight; the actual indicator series lives in the
    indicator catalog (Phase 94) and is dereferenced via citation grammar
    (``ref:indicator:<indicator_id>``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    indicator_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    weight: float = Field(
        ge=0.0,
        le=1.0,
        description="Relative weight of this indicator in the domain's health_score.",
    )


class DomainEdge(BaseModel):
    """Directed edge from this Domain to a related Domain.

    Used to render the macro-relationship map and to drive cross-domain
    propagation (Phase 95 Plan 11 — DomainEngine).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_slug: str = Field(
        min_length=1,
        description="Target Domain.slug (one of the canonical 12).",
    )
    strength: float = Field(ge=0.0, le=1.0)
    relationship: str = Field(
        min_length=1,
        description="Short label (e.g., 'reinforces', 'lags', 'inverse').",
    )


class Domain(BaseSection):
    """Typed contract for one of the 12 canonical macro Domains (CONTEXT §A/§C).

    Extends BaseSection — inherits frozen + extra='forbid' + the standard
    envelope (snapshot_id, version, generated_at, status, provenance, …).
    """

    # --- Identity (matches domain_catalog.yaml entry) ---
    domain_id: str = Field(min_length=1)
    slug: str = Field(
        min_length=1,
        description=(
            "URL slug — same as domain_id by convention "
            "(Plan 13 frontend route registry assumes this)."
        ),
    )
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    importance: int = Field(
        ge=1,
        le=12,
        description="Display-order rank 1..12 (REQ-95-1 locks 12 domains).",
    )
    primary_pillars: list[str] = Field(
        min_length=1,
        description=(
            "Non-empty subset of {Growth, Inflation, Liquidity, Risk}. "
            "Each domain feeds at least one analytical pillar (CONTEXT §B)."
        ),
    )
    primary_analyst: str = Field(
        min_length=1,
        description="AgentId of the primary domain analyst (e.g., vm107.growth_domain_analyst).",
    )

    # --- Computed health metrics (filled by DomainEngine, Plan 11) ---
    health_score: float = Field(ge=0.0, le=100.0)
    trend_score: float = Field(ge=-100.0, le=100.0)
    breadth_score: float = Field(ge=0.0, le=100.0)
    headline: str = Field(
        min_length=1,
        description="One-line headline for the Domain card.",
    )
    risk_level: Literal["low", "medium", "high", "critical"]
    current_state: Literal[
        "Accelerating",
        "Improving",
        "Stable",
        "Slowing",
        "Deteriorating",
        "Reversing",
    ]

    # --- Narrative payload ---
    drivers: list[Driver]
    constraints: list[str]
    tailwinds: list[str]
    headwinds: list[str]

    # --- Relationships ---
    top_indicators: list[IndicatorRef]
    related_domains: list[DomainEdge]
    related_themes: list[str]
    latest_releases: list[str]

    @field_validator("primary_pillars")
    @classmethod
    def _primary_pillars_subset(cls, value: list[str]) -> list[str]:
        unknown = set(value) - _VALID_PILLARS
        if unknown:
            raise ValueError(
                "primary_pillars must be a subset of "
                f"{sorted(_VALID_PILLARS)}; got unknown: {sorted(unknown)}"
            )
        return value
