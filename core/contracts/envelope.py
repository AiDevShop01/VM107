"""
Phase 44 AgentEnvelope schema and schema-version validation helper.

AgentEnvelope is the A2A observability unit — one envelope per agent invocation.
Persisted to MongoDB agent_envelopes collection (migration 007).

Design notes:
- Extends CapabilityProvenanceMixin (Phase 47.6 LD-10) + BaseModel — the 3
  provenance stamping fields are required on every write. No defaults on
  registry_snapshot_hash or registry_snapshot_generated_at (Pitfall 5).
- _id in MongoDB = envelope_id (str uuid4), matching Phase 43.2 convention.
- schema_version bumped to 2 in Phase 47.6 (RESEARCH Open Q5).
  Legacy schema_version=1 documents are readable via read_envelope_tolerant().
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, Field

from core.contracts.exceptions import SchemaVersionMismatchError
from fingpt_core.provenance import CapabilityProvenanceMixin
from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6


class AgentEnvelope(CapabilityProvenanceMixin, BaseModel):
    """
    A2A agent invocation envelope — Phase 47.6 provenance-stamped (LD-10).

    One instance per agent invocation (Idea Agent, Strategy Agent, or Coordinator).
    Captures input, output, cost, routing decisions, and provenance links.

    Fields:
        envelope_id: UUID4 string — MongoDB _id
        task_id: Links to Phase 42 task (or "api-<uuid>" for direct HTTP calls)
        parent_task_id: Optional parent task for nested invocation chains
        agent_id: Routing identity — "agent_zero" | "idea_agent" | "strategy_agent"
        input: Serialized input payload (dict)
        output: Serialized output payload or PlainTextResult on degraded
        model_used: Actual model called (chain-index aware from Phase 43.2 router)
        cost: {tokens, cost_usd, latency_ms} from Phase 43.2 CostRecord
        reason_chain: Router decision tags list
        source_envelope_id: Hypothesis.source_envelope_id provenance link
        schema_version: Bumped to 2 in Phase 47.6 (RESEARCH Open Q5)
        status: Invocation outcome — success, failure, or degraded
        timestamp: UTC timestamp of envelope creation

    CapabilityProvenanceMixin contributes (required, no defaults):
        registry_snapshot_hash: str  — 8..64 char hex digest
        registry_snapshot_generated_at: datetime
        registry_schema_version: str  — defaults to "1.0"
    """

    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    parent_task_id: Optional[str] = None
    agent_id: str  # "agent_zero" | "idea_agent" | "strategy_agent"
    input: dict
    output: dict
    model_used: str
    cost: dict  # {tokens, cost_usd, latency_ms}
    reason_chain: list[str]
    source_envelope_id: Optional[str] = None
    journal_id: Optional[str] = None
    schema_version: int = 2  # bumped from 1 in Phase 47.6 per RESEARCH Open Q5
    status: Literal["success", "failure", "degraded"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def read_envelope_tolerant(doc: dict) -> AgentEnvelope:
    """Read a schema_version=1 OR =2 document. Backfills sentinel if pre-47.6 cohort.

    Phase 47.6 backward-compatibility helper. Prevents crashes when reading
    pre-47.6 agent_envelopes that lack the 3 provenance fields.

    Args:
        doc: Raw MongoDB document dict (not mutated by this function).

    Returns:
        AgentEnvelope with provenance fields backfilled if missing.
    """
    if doc.get("schema_version", 1) == 1:
        doc = dict(doc)  # avoid mutating input
        doc["schema_version"] = 2
        doc.setdefault("registry_snapshot_hash", REGISTRY_SNAPSHOT_PRE_47_6)
        doc.setdefault(
            "registry_snapshot_generated_at",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        doc.setdefault("registry_schema_version", "0.0")
        # Plan 06 fields (pre-populated so tolerant reader stays compatible):
        doc.setdefault("capability_introspection_log", [])
        doc.setdefault("capability_refusal_log", [])
    return AgentEnvelope(**doc)


def validate_envelope_schema_version(
    envelope: AgentEnvelope, expected: int = 2
) -> AgentEnvelope:
    """
    Validate that an envelope's schema_version matches the expected version.

    Per CONTEXT.md § A2A Envelope Structure: strict fail-fast — NO implicit migration.
    On mismatch: raise SchemaVersionMismatchError(expected, received) immediately.

    Args:
        envelope: The AgentEnvelope to validate.
        expected: The expected schema version (default 1).

    Returns:
        The envelope unchanged if versions match.

    Raises:
        SchemaVersionMismatchError: If envelope.schema_version != expected.
    """
    if envelope.schema_version != expected:
        raise SchemaVersionMismatchError(expected=expected, received=envelope.schema_version)
    return envelope
