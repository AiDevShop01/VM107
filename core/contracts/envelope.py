"""
Phase 44 AgentEnvelope schema and schema-version validation helper.

AgentEnvelope is the A2A observability unit — one envelope per agent invocation.
Persisted to MongoDB agent_envelopes collection (migration 007).

Design notes:
- Extends BaseModel (NOT BaseContract) — envelope is observability metadata,
  not a typed-payload contract. No frozen=True here; model_dump() flexibility
  needed for MongoDB serialization.
- _id in MongoDB = envelope_id (str uuid4), matching Phase 43.2 convention.
- schema_version follows int convention from CONTEXT.md § A2A Envelope Structure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, Field

from core.contracts.exceptions import SchemaVersionMismatchError


class AgentEnvelope(BaseModel):
    """
    A2A agent invocation envelope.

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
        schema_version: Strict version — raises SchemaVersionMismatchError on mismatch
        status: Invocation outcome — success, failure, or degraded
        timestamp: UTC timestamp of envelope creation
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
    schema_version: int = 1
    status: Literal["success", "failure", "degraded"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def validate_envelope_schema_version(
    envelope: AgentEnvelope, expected: int = 1
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
