"""Country — Phase 96 REQ-96-2 catalog row contract.

Single source of truth for the 246-country catalog is
``contracts/economic_intelligence/country_catalog.yaml`` in the Dagster repo
(Pitfall 5 lock — no hand-list drift). This Pydantic model validates each
row's shape so the catalog YAML cannot accept malformed data.

Vendored to 4 fingpt_core copies per Phase 95-09 pattern:
- Dagster/fingpt_core/src/fingpt_core/...
- VM100/backend/fingpt_core_pkg/src/fingpt_core/...
- VM102/backend/fingpt_core_pkg/src/fingpt_core/...
- VM107/contracts/...

Byte-equality across the 4 copies is enforced by
``contracts/economic_intelligence/tests/test_country_contracts.py``.

Frozen + extra='forbid' per Phase 38 typed-contract lock.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ISO_ALPHA2 = re.compile(r"^[A-Z]{2}$")
_ISO_NUMERIC = re.compile(r"^\d{3}$")


class Country(BaseModel):
    """One row of the canonical country catalog (REQ-96-2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iso_alpha2: str = Field(
        ...,
        description="ISO 3166-1 alpha-2 code (UPPERCASE 2 letters).",
    )
    iso_numeric: str = Field(
        ...,
        description=(
            "ISO 3166-1 numeric (zero-padded 3-digit string — e.g. '840' "
            "for US). Used by react-simple-maps TopoJSON `geometry.id` "
            "lookup in Plan 96-09."
        ),
    )
    gec_code: str | None = Field(
        default=None,
        description=(
            "CIA GEC 2-letter code (lowercase — e.g. 'us'). Used as the "
            "Factbook filename stem in Plan 96-07. May be None for "
            "ISO-listed countries that lack a Factbook profile (Aruba, "
            "Åland, Western Sahara, etc.)."
        ),
    )
    name: str = Field(
        ...,
        min_length=2,
        description="Human-readable ISO 3166-1 common name (e.g. 'United States').",
    )
    region: Literal[
        "africa", "americas", "asia", "europe", "oceania", "antarctica", "world"
    ] = Field(
        ...,
        description=(
            "Coarse-grained region bucket used by World Map filters "
            "(REQ-96-1) and Country Page navigation (REQ-96-2)."
        ),
    )
    has_factbook_profile: bool = Field(
        default=True,
        description=(
            "True for the ~243 ISO codes with a corresponding CIA Factbook "
            "profile loaded into ref_country_profiles. False for the handful "
            "(Aruba, Åland, etc.) that need ECONOMY-sentiment fallback or "
            "later Phase 97 dynamic ingestion."
        ),
    )

    @field_validator("iso_alpha2")
    @classmethod
    def _validate_alpha2(cls, value: str) -> str:
        if not _ISO_ALPHA2.match(value):
            raise ValueError(
                f"iso_alpha2 must match ^[A-Z]{{2}}$ (uppercase 2 letters); got {value!r}"
            )
        return value

    @field_validator("iso_numeric")
    @classmethod
    def _validate_numeric(cls, value: str) -> str:
        if not _ISO_NUMERIC.match(value):
            raise ValueError(
                f"iso_numeric must match ^\\d{{3}}$ (zero-padded 3 digits); got {value!r}"
            )
        return value
