"""Phase 44 envelope persistence.

Writes AgentEnvelope to MongoDB agent_envelopes collection using the
Phase 43.2 convention (_id = envelope_id = str(uuid4())).

Public API:
    build_envelope() — construct an AgentEnvelope from subordinate invocation result
    write_envelope() — persist to MongoDB, returns envelope_id
"""
from __future__ import annotations

import logging
from typing import Optional

from core.contracts.envelope import AgentEnvelope

log = logging.getLogger(__name__)


def build_envelope(
    *,
    task_id: str,
    parent_task_id: Optional[str],
    agent_id: str,
    input_payload: dict,
    output_payload: dict,
    telemetry: dict,
    status: str,  # "success" | "failure" | "degraded"
    source_envelope_id: Optional[str] = None,
    journal_id: Optional[str] = None,
) -> AgentEnvelope:
    """Construct an AgentEnvelope from a subordinate invocation result + telemetry.

    Args:
        task_id: Phase 42 task identifier (or "api-<uuid>" for direct HTTP calls).
        parent_task_id: Optional parent task for nested invocation chains.
        agent_id: Routing identity — "agent_zero" | "idea_agent" | "strategy_agent".
        input_payload: Serialized input dict.
        output_payload: Serialized output dict (or degraded PlainTextResult dict).
        telemetry: Router telemetry dict with model_used, reason_chain, cost, fallback_used.
        status: Invocation outcome — "success", "failure", or "degraded".
        source_envelope_id: Idea envelope_id for Strategy envelope provenance chain.
        journal_id: Phase 47 journal-anchored chat thread identifier (None for non-chat
            invocations; sparse-indexed in MongoDB).

    Returns:
        AgentEnvelope ready for persistence.
    """
    return AgentEnvelope(
        task_id=task_id,
        parent_task_id=parent_task_id,
        agent_id=agent_id,
        input=input_payload,
        output=output_payload,
        model_used=telemetry.get("model_used", "unknown"),
        cost=telemetry.get("cost", {}),
        reason_chain=list(telemetry.get("reason_chain", [])),
        source_envelope_id=source_envelope_id,
        journal_id=journal_id,
        status=status,  # type: ignore[arg-type]  # Pydantic validates Literal
    )


def write_envelope(db, envelope: AgentEnvelope) -> str:
    """Insert envelope into agent_envelopes collection. Returns _id (= envelope_id).

    Phase 43.2 convention: _id = envelope_id (str(uuid4)). This collapses
    envelope_id and MongoDB's _id, simplifying provenance queries.

    Args:
        db: MongoDB database handle (pymongo.Database or test double).
        envelope: AgentEnvelope to persist.

    Returns:
        envelope_id string (= the MongoDB _id that was inserted).

    Raises:
        Exception: Re-raised if MongoDB insert fails (after logging).
    """
    doc = envelope.model_dump(mode="json")  # datetime → ISO string
    doc["_id"] = envelope.envelope_id  # explicit primary key per Phase 43.2 convention
    try:
        db["agent_envelopes"].insert_one(doc)
    except Exception as exc:
        log.error(
            "failed to persist agent_envelope envelope_id=%s: %s",
            envelope.envelope_id,
            exc,
        )
        raise
    return envelope.envelope_id
