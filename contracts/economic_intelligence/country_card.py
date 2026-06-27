"""CountryCardSection — Phase 94 §P.

Country profile + 3–4 'economic DNA' tags. Joined from ref_country_profiles
and country_attributes tables.
"""

from __future__ import annotations

from pydantic import Field

from .base_section import BaseSection


class CountryCardSection(BaseSection):
    """Country profile + DNA tags."""

    country: str = Field(min_length=2, max_length=2)
    display_name: str = Field(min_length=1)
    flag_emoji: str = Field(min_length=1)
    economy_size_usd_bn: float = Field(ge=0.0)
    dna_tags: list[str] = Field(
        min_length=1,
        max_length=8,
        description="3–4 'economic DNA' tags (e.g., 'commodity-export').",
    )
    profile_link: str = Field(
        min_length=1,
        description="Phase 96 deep-link to the country profile page.",
    )
