"""Pydantic schema for ``contract`` capability registry entries (Phase 74).

Phase 74 introduces the ``contract`` capability type as the Phase 47.6
mandatory namespace for cross-VM Pydantic contracts.  Every shared contract
(Observation, NotificationContract, SupervisoryObservation, …) must carry a
matching ``VM107/registry/contract/<id>.yaml`` entry validated by this schema.

Boot-validation: Phase 47.6 loader rejects any entry with
``type: contract`` that doesn't satisfy ContractCapability.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ContractCapability(BaseModel):
    """Capability registry entry for a cross-VM Pydantic contract."""

    id: str
    type: Literal["contract"]
    status: Literal["real", "partial", "planned", "deprecated"]
    shipped: int
    planned_phase: Optional[int] = None
    last_changed: str  # ISO date (YYYY-MM-DD) — keep quoted in YAML

    name: str
    description: str
    owner_vm: str  # "fingpt_core" for cross-VM; specific VM for VM-only

    contract_version: str  # e.g. "1.0" — bump on breaking schema changes
    source_module: str  # Python import path of the canonical Pydantic class

    # List every field name from the Pydantic class (documentation + diff aid)
    fields: list[str] = Field(default_factory=list)

    # WORM lock: True means rows are append-only — no UPDATE ever
    worm: bool = False

    # Phase 47.6 forward-compat
    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
