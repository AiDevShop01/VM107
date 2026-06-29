"""Country search — Phase 96 REQ-96-8 cross-country Qdrant search contracts.

Pydantic request/response contracts for the `find_countries_by_profile_query`
tool (VM107/tools/find_countries_by_profile_query.py). The tool semantic-searches
the Qdrant `country_profiles` collection (per-country narrative section vectors)
and returns a ranked, deduplicated country list with section evidence.

Vendored to 2 copies per Phase 95-09 pattern:
- Dagster/fingpt_core/src/fingpt_core/contracts/economic_intelligence/country_search.py
- VM107/contracts/economic_intelligence/country_search.py

(VM100/VM102 do not consume this contract — VM107-internal only.)

Registry YAML (VM107/registry/tool/vm107.tool.find_countries_by_profile_query.yaml)
locks these import paths:
- request_contract:  FindCountriesByProfileRequest
- response_contract: FindCountriesByProfileResponse
- contracts.request:  fingpt_core.contracts.economic_intelligence.country_search.FindCountriesByProfileRequest
- contracts.response: fingpt_core.contracts.economic_intelligence.country_search.FindCountriesByProfileResponse

CountryHit is NOT frozen because section_evidence is appended to during the
dedup-by-country aggregation pass in the tool. Final CountryHit objects are
constructed only after aggregation completes (extra='forbid' still applies).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FindCountriesByProfileRequest(BaseModel):
    """Request — natural-language profile query against country_profiles collection.

    Plan 96-06 must_haves:
    - section_filter narrows to one section_type (e.g. 'ECONOMY') via Qdrant
      Filter(must=[FieldCondition(key='section_type', match=MatchValue(...))])
    - country_filter restricts to a subset of ISO alpha-2 codes via MatchAny
    - min_score gates hits below similarity threshold (cosine-normalised [0,1])
    - top_k caps unique countries returned (post-dedup)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(
        ...,
        min_length=3,
        description="Natural-language profile query (e.g. 'reserve currency issuer with floating exchange rate').",
    )
    section_filter: str = Field(
        default="",
        description="Optional section_type narrowing (ECONOMY/ENERGY/GOVERNMENT/etc.). Empty = no narrowing.",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max unique countries returned (post-dedup-by-country).",
    )
    min_score: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity threshold; hits below are discarded.",
    )
    country_filter: list[str] | None = Field(
        default=None,
        description="Optional ISO alpha-2 subset (e.g. ['US','GB','JP']). None = no restriction.",
    )


class CountryHit(BaseModel):
    """One country in the ranked response — built up via dedup-by-country aggregation.

    extra='forbid' but NOT frozen so the tool can append additional section
    evidence as it walks the Qdrant hit stream. The tool constructs final
    CountryHit objects only after aggregation completes.
    """

    model_config = ConfigDict(extra="forbid")

    iso_alpha2: str = Field(..., description="ISO 3166-1 alpha-2 country code.")
    country_name: str = Field(..., description="Human-readable country name.")
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Best section score for this country (cosine similarity).",
    )
    section_evidence: list[dict] = Field(
        ...,
        description=(
            "Up to 3 section-level evidence dicts (section_type, section_id, "
            "narrative_snippet ≤ 200 chars, score). Highest-scoring section per "
            "country kept first; additional sections appended in score order."
        ),
    )


class FindCountriesByProfileResponse(BaseModel):
    """Response — ranked unique-country list + structured-logging metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    countries: list[CountryHit] = Field(
        default_factory=list,
        description="Up to top_k unique countries, sorted by score descending.",
    )
    query_hash: str = Field(
        ...,
        description="Stable hash of the query string for log correlation (MD5 hex).",
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="End-to-end latency including embedding + Qdrant + dedup, in milliseconds.",
    )


__all__ = [
    "FindCountriesByProfileRequest",
    "CountryHit",
    "FindCountriesByProfileResponse",
]
