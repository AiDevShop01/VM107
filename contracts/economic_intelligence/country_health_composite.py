"""CountryHealthComposite — Phase 96 REQ-96-1 World Map heatmap payload.

The World Map at `/markets/world` (Plan 96-09) needs a bulk endpoint that
returns one composite score per country in a single fetch (avoid per-country
fan-out — RESEARCH.md §REQ-96-1). This file defines the wire shape of that
endpoint:

    GET /api/macro-situation/world/health-composite
    → WorldHealthCompositePayload{
        countries: { "US": CountryHealthComposite, "JP": …, … }
      }

US carries the real Phase 94 Health Pillars composite from day 1. The other
245 countries fall back to a polarity-scored CIA Factbook ECONOMY section
narrative until Phase 97 lights up multi-country dynamic ingestion — see
RESEARCH.md §REQ-96-1 for the fallback strategy.

All three payload fields are nullable to allow the fallback path to ship
"unknown" countries cleanly (the resolver emits the row with `None`s rather
than dropping it so the World Map can colour-code missing-data states).

Frozen + extra='forbid' per Phase 38 typed-contract lock.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ISO_ALPHA2 = re.compile(r"^[A-Z]{2}$")


class CountryHealthComposite(BaseModel):
    """One country's row in the World Map bulk heatmap payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iso_alpha2: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 (UPPERCASE) — joins to country_catalog.",
    )
    composite_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description=(
            "Composite health score in [0, 100]. None when no data is "
            "available yet (Factbook-only fallbacks pre-polarity-scoring)."
        ),
    )
    regime_state: Literal["RISK_ON", "RISK_OFF", "NEUTRAL"] | None = Field(
        default=None,
        description=(
            "Coarse-grained risk regime classification. None when no data "
            "is available yet."
        ),
    )
    last_updated: datetime | None = Field(
        default=None,
        description=(
            "UTC timestamp when the composite was last recomputed. None "
            "when no data is available yet."
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


class WorldHealthCompositePayload(BaseModel):
    """Bulk World Map endpoint envelope (REQ-96-1).

    Keys are ISO 3166-1 alpha-2 strings; values are per-country composites.
    A single fetch returns all 246 catalog rows so the World Map can render
    in one paint (Pitfall: per-country fan-out is explicitly avoided).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    countries: dict[str, CountryHealthComposite] = Field(
        default_factory=dict,
        description=(
            "ISO alpha-2 keyed map of composites. Always populated for all "
            "catalog rows so missing-data states render explicitly rather "
            "than as absent map cells."
        ),
    )
