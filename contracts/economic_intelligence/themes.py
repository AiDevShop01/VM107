"""ThemeMonitorSection — Phase 94 §H + Phase 95 Plan 14 §I.

Themes have an 8-state lifecycle and a strength score (0..100). The state
machine is implemented in VM107 theme_engine; this contract is the wire
format.

Phase 95 Plan 14 addition — `Theme.affected_domains: list[DomainId]`
-------------------------------------------------------------------
Bridges Phase 94 Theme Monitor to the Phase 95 Domain Pages. Each theme
declares zero or more of the canonical 12 macro domain slugs (CONTEXT §A).
Default `[]` keeps every existing Phase 94 theme valid (Open Q 3 resolution
— backwards compat MUST hold). The frontend `ThemeCard` click handler reads
this field and:

- 0 domains → falls through to existing Phase 94 click target (legacy).
- 1 domain → router.push(`/markets/macro/domain/<slug>`).
- >1 domains → opens `ThemeDomainDisambiguator` dropdown.

Domain Page §8 (Related Themes) reverse-links via
``affected_domains contains <this_domain_id>``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


# CONTEXT §A — canonical 12 macro domain slugs (locked 2026-06-28).
# Single source of truth for the YAML catalog is
# ``contracts/economic_intelligence/domain_catalog.yaml`` but the validator
# inlines the set to avoid a fingpt_core → YAML I/O dependency. Any drift is
# caught by tests/contracts/economic_intelligence/test_theme_contract.py.
CANONICAL_DOMAIN_SLUGS: frozenset[str] = frozenset(
    {
        "growth",
        "inflation",
        "labour",
        "housing",
        "credit",
        "monetary_policy",
        "fiscal",
        "external_sector",
        "manufacturing",
        "consumer",
        "financial_conditions",
        "commodities",
    }
)


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
    # Phase 95 Plan 14 — Theme→Domain forward-link. Default [] = backwards
    # compatible with every Phase 94 theme already in flight.
    affected_domains: list[str] = Field(
        default_factory=list,
        description=(
            "Subset of canonical 12 macro domain slugs this theme touches. "
            "Empty list = preserve legacy Phase 94 click target."
        ),
    )

    @field_validator("affected_domains")
    @classmethod
    def _validate_affected_domains_subset(cls, value: Any) -> list[str]:
        if not isinstance(value, list):  # pragma: no cover — pydantic guards
            raise TypeError("affected_domains must be a list of strings")
        unknown = [s for s in value if s not in CANONICAL_DOMAIN_SLUGS]
        if unknown:
            raise ValueError(
                "affected_domains contains unknown slug(s) "
                f"{unknown!r}; must be subset of CONTEXT §A canonical 12 "
                f"({sorted(CANONICAL_DOMAIN_SLUGS)})."
            )
        return value


class ThemeMonitorSection(BaseSection):
    """Section payload for theme monitoring."""

    themes: list[Theme] = Field(
        description="All active themes (excluding ARCHIVED).",
    )
