"""EconomicDnaTag — Phase 96 REQ-96-4 country DNA tag contract.

The Economic DNA agent (Plan 96-05) condenses each country's CIA Factbook
sections + relationship graph into a short list of typed DNA tags
(e.g. "reserve-currency-issuer", "small-open-economy", "commodity-exporter").

Every tag MUST carry:
- a stable tag_id (snake / kebab) so downstream agents can pattern-match;
- a human-readable label for UI rendering;
- a confidence in [0, 1] explaining how strongly the source evidence
  supports the claim;
- at least one provenance section id (REQ-96-4 hard lock — no
  unjustified tag may ship);
- zero or more Neo4j graph paths that re-prove the claim from the
  relationship graph (Plan 96-02).

Frozen + extra='forbid' per Phase 38 typed-contract lock.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EconomicDnaTag(BaseModel):
    """One DNA tag produced by the Country DNA generator (Plan 96-05)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_id: str = Field(
        min_length=1,
        description=(
            "Stable kebab/snake-case tag identifier (e.g. "
            "'reserve-currency-issuer', 'commodity-exporter')."
        ),
    )
    label: str = Field(
        min_length=1,
        description="Human-readable label rendered on the Economic DNA tab.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Strength of the supporting evidence in [0, 1].",
    )
    provenance_sections: list[int] = Field(
        min_length=1,
        description=(
            "ref_country_profile_sections.id values that justify this tag. "
            "Must be non-empty (REQ-96-4 hard lock — no unjustified tags)."
        ),
    )
    provenance_graph_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Optional Cypher-style path strings from the Neo4j country "
            "graph (Plan 96-02) that independently re-prove the claim. "
            "May be empty when the section evidence alone is sufficient."
        ),
    )
