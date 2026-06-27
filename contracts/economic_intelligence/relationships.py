"""RelationshipSection — Phase 94 §G.

Empirical relationships between indicators / regimes. Drawn from Phase 87
macro graph + transmission analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection


class Relationship(BaseModel):
    """A single directed relationship."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_node: str = Field(min_length=1)
    to_node: str = Field(min_length=1)
    relationship: str = Field(min_length=1)
    strength: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)


class RelationshipSection(BaseSection):
    """Relationship section payload."""

    edges: list[Relationship]
