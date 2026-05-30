"""Phase 73 — Pydantic schema for ``opportunity_lifecycle`` capability entries.

Every ``OpportunityState`` value in
``mission_control.contracts.opportunity_lifecycle.OpportunityState`` must
have a matching ``VM107/registry/opportunity_lifecycle/<id>.yaml`` entry
validated by this schema. Drift -> ``RegistryValidationError`` at boot.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


LifecycleColor = Literal["info", "warning", "success", "danger", "neutral"]


class OpportunityLifecycleStateSpec(BaseModel):
    """Capability registry entry for an opportunity lifecycle state."""

    id: str
    type: Literal["opportunity_lifecycle"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str

    state_name: str  # MUST match an OpportunityState enum value
    display_name: str
    color: LifecycleColor
    progress: int = Field(ge=0, le=100)
    entered_via_events: list[str] = Field(default_factory=list)
    exited_via_events: list[str] = Field(default_factory=list)
    description: str

    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
