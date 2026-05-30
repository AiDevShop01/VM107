"""Phase 73 — Pydantic schema for ``workflow_intent`` capability registry entries.

Every ``WorkflowIntentType`` value in
``fingpt_core.contracts.workflow.WorkflowIntentType`` must have a matching
``VM107/registry/workflow_intent/<id>.yaml`` entry validated by this schema
(Phase 47.6 lock). Drift between the enum and the filesystem causes the
boot-fast validator to raise ``RegistryValidationError``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


SelectionTypeSupported = Literal["opportunity", "position", "trade", "idea"]


class WorkflowIntentSpec(BaseModel):
    """Capability registry entry for a workflow intent type."""

    id: str
    type: Literal["workflow_intent"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str  # ISO date (YYYY-MM-DD)

    intent_type: str  # MUST match a WorkflowIntentType enum value
    selection_types_supported: list[SelectionTypeSupported] = Field(
        default_factory=list
    )
    required_guards: list[str] = Field(default_factory=list)
    dispatch_target: str  # domain event type id, or literal "none"
    description: str

    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
