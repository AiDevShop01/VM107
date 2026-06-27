"""ProvenanceObject — Phase 94 §F.7 provenance contract.

Every section (and every Pillar) carries one of these. It captures which
upstream events/agents/weights produced the value and the data versions of
the underlying typed APIs, so downstream tooling can replay or invalidate
deterministically.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProvenanceObject(BaseModel):
    """Provenance of a single section (or pillar) output.

    Frozen + extra='forbid' per Phase 38 typed-contract lock.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_event_ids: list[str] = Field(
        description="EconomicEvent.event_id values that contributed to this output.",
    )
    weights_version: str = Field(
        min_length=1,
        description=(
            "YAML weights file version used by deterministic engines "
            "(e.g., pillar_engine, theme_engine)."
        ),
    )
    model_version: str = Field(
        min_length=1,
        description="LLM/model identifier (e.g., 'claude-3-5-sonnet-20241022', 'na').",
    )
    prompt_version: str = Field(
        min_length=1,
        description="Prompt template version. 'na' for non-LLM engines.",
    )
    upstream_sections: list[str] = Field(
        description="Section IDs whose output this section consumed.",
    )
    data_versions: dict[str, int] = Field(
        description=(
            "Typed-API data versions consumed (e.g., "
            "{'vm101.economic_event': 12, 'vm107.regime': 3})."
        ),
    )
