"""CountryTabSection — Phase 96 REQ-96-2 Country Page tab payload.

One of the 14 tabs rendered by the Country Page shell (Plan 96-10):
- 12 CIA Factbook profile sections: INTRODUCTION, GEOGRAPHY, PEOPLE,
  ENVIRONMENT, GOVERNMENT, ECONOMY, ENERGY, COMMUNICATIONS,
  TRANSPORTATION, MILITARY, TERRORISM, TRANSNATIONAL_ISSUES.
- 2 fingpt-added tabs: ECONOMIC_DNA (Plan 96-05), KNOWLEDGE_GRAPH (Plan 96-11).

Inherits BaseSection (Phase 94 §D) so it ships with the full envelope:
status (6-state degradation), provenance, freshness_seconds, version,
confidence, citations, limitations, etc. The Country Page can render
generically against this envelope, and the snapshot coordinator can
incrementally regenerate per-tab without touching siblings.

Narrative HTML is pre-sanitised via bleach (Plan 96-03) — see
``feedback_ui_phase_verify_with_render_chain`` for the XSS guard contract.

Attributes carry the Factbook EAV row shape from
``ref_country_profile_sections`` (RESEARCH.md §REQ-96-3 / §Open Q 7).

Frozen + extra='forbid' inherited from BaseSection. Do not relax.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base_section import BaseSection

_ISO_ALPHA2 = re.compile(r"^[A-Z]{2}$")


class CountryAttribute(BaseModel):
    """One row from the Factbook EAV attribute table.

    Mirrors ``ref_country_profile_attributes`` columns used by Plan 96-10
    to render the per-tab attribute lists alongside the narrative HTML.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(
        min_length=1,
        description="Snake-case attribute key (e.g. 'gdp_ppp', 'population_total').",
    )
    value: str = Field(
        description=(
            "Original Factbook display string preserved verbatim — "
            "may include units, qualifiers, year suffix."
        ),
    )
    numeric_value: float | None = Field(
        default=None,
        description="Best-effort numeric coercion of `value` (None when non-numeric).",
    )
    unit: str | None = Field(
        default=None,
        description="Parsed unit (e.g. 'USD', '%', 'km2'). None when not detectable.",
    )
    year: int | None = Field(
        default=None,
        description="Reference year extracted from the value, when present.",
    )
    rank: int | None = Field(
        default=None,
        description="Factbook-published world rank for the attribute, when present.",
    )
    comparison_to_world: str | None = Field(
        default=None,
        description="Factbook's natural-language comparison line, when present.",
    )


class CountryTabSection(BaseSection):
    """One tab of a Country Page (REQ-96-2).

    Extends BaseSection — inherits frozen + extra='forbid' + the standard
    envelope (snapshot_id, version, generated_at, status, provenance, …).
    """

    # --- Identity ---
    iso_alpha2: str = Field(
        min_length=2,
        max_length=2,
        description="Owning country (ISO 3166-1 alpha-2 UPPERCASE).",
    )
    tab_id: Literal[
        # 12 CIA Factbook profile sections (`ref_profile_types.code`).
        "INTRODUCTION",
        "GEOGRAPHY",
        "PEOPLE",
        "ENVIRONMENT",
        "GOVERNMENT",
        "ECONOMY",
        "ENERGY",
        "COMMUNICATIONS",
        "TRANSPORTATION",
        "MILITARY",
        "TERRORISM",
        "TRANSNATIONAL_ISSUES",
        # 2 fingpt-added tabs.
        "ECONOMIC_DNA",
        "KNOWLEDGE_GRAPH",
    ] = Field(
        description=(
            "Tab discriminator. 12 Factbook profile sections + 2 fingpt "
            "tabs (Economic DNA, Knowledge Graph view) = 14 total."
        ),
    )

    # --- Tab payload ---
    narrative_html: str = Field(
        default="",
        description=(
            "Bleach-sanitised narrative HTML (Phase 92 sanitisation helpers). "
            "Empty string when the tab is purely attribute-driven."
        ),
    )
    attributes: list[CountryAttribute] = Field(
        default_factory=list,
        description=(
            "EAV-folded attribute rows from ref_country_profile_attributes. "
            "Empty list when the tab is purely narrative."
        ),
    )

    @field_validator("iso_alpha2")
    @classmethod
    def _validate_iso(cls, value: str) -> str:
        if not _ISO_ALPHA2.match(value):
            raise ValueError(
                f"iso_alpha2 must match ^[A-Z]{{2}}$ (uppercase 2 letters); got {value!r}"
            )
        return value
