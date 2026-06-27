"""SpecialistResponse — Phase 94 §M router/synthesizer contract.

The typed return shape every specialist agent emits when invoked by the
chief_economist_synthesizer. Open evidence list (dict) lets each specialist
ship its own evidence schema while keeping the outer envelope rigid.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SpecialistResponse(BaseModel):
    """A specialist agent's typed response (per §M)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[str] = Field(
        description="Citation grammar refs.",
    )
    evidence: list[dict[str, Any]] = Field(
        description="Per-specialist evidence records (open dict shape).",
    )
    limitations: list[str] = Field(
        description="Human-readable caveats.",
    )
    related_entities: list[str] = Field(
        description=(
            "Cross-references to other entities "
            "(e.g., 'pillar:Growth', 'country:US')."
        ),
    )
    schema_version: str = Field(default="1", min_length=1)
