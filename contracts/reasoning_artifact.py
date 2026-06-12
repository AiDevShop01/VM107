"""Brain B1 — Persistent Reasoning Artifact contract.

Verbatim 15-field schema from Brain Part 2 §B1 lines 184-203.
Do NOT diverge from this schema — it is a D6 lock per Phase 85 ARCHITECTURE.md.

CitationRef is defined locally here (not imported from fingpt_core.contracts.evidence)
because EvidenceCitation in fingpt_core uses a different field shape
(citation_kind / opaque_id / human_label) oriented toward Phase 70.5 tool results.
B1 citations are simpler audit references (citation_id / source / snippet) as
specified in Brain Part 2 §B1. Using a local definition keeps the B1 contract
self-contained and avoids silent field mismatches.

Phase 85 Plan 02 — frozen=True enforces WORM at the application layer
(defense in depth alongside DB-level REVOKE UPDATE/DELETE from PUBLIC).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CitationRef(BaseModel):
    """A lightweight audit citation attached to a reasoning artifact.

    Intentionally simpler than fingpt_core.contracts.evidence.EvidenceCitation
    — these are ad-hoc reasoning references, not structured evidence contracts.
    """

    citation_id: str
    source: str
    snippet: str | None = None

    model_config = {"frozen": True}


class ReasoningArtifactContract(BaseModel):
    """B1 Persistent Reasoning Artifact — verbatim Brain Part 2 §B1 schema.

    15 fields (16 columns in DB — artifact_id is the PK):
      artifact_id, agent_profile_id, sub_profile_id, iteration,
      parent_envelope_id, reasoning_text, reasoning_tokens, response_text,
      response_tokens, tool_called, tool_args, timestamp, model_version,
      prompt_version, confidence_self_report, citations

    Frozen contract — mutation raises ValidationError. Matches DB-level WORM
    (no UPDATE/DELETE grants for the VM107 role).
    """

    artifact_id: UUID
    agent_profile_id: str
    sub_profile_id: str | None = None
    iteration: int
    parent_envelope_id: UUID | None = None
    reasoning_text: str
    reasoning_tokens: int
    response_text: str
    response_tokens: int
    tool_called: str | None = None
    tool_args: dict | None = None
    timestamp: datetime
    model_version: str
    prompt_version: str
    confidence_self_report: float | None = None   # Filled by future B5; null in Phase 85
    citations: list[CitationRef] = Field(default_factory=list)

    model_config = {"frozen": True}
