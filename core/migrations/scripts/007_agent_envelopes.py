"""Migration 007 — agent_envelopes collection (Phase 44 A2A envelopes).

Creates collection + 4 indexes per CONTEXT.md § A2A Envelope Structure:
  - task_id (lineage queries)
  - source_envelope_id (provenance traversal, sparse — most envelopes have no parent)
  - agent_id + timestamp (per-agent recent activity)
  - timestamp (recent envelopes, descending)

Notes:
  - Migration is NOT automatically executed. Run via the VM107 migration runner or
    a Dagster deploy checkpoint.
  - No JSON-schema validator on the collection — strict validation lives in Pydantic
    (AgentEnvelope), not Mongo. Matches agent_runs stub-validator precedent from
    migration 001.
  - MongoDB _id = envelope_id (str uuid4), matching Phase 43.2 convention.
  - Downgrade drops the entire collection (no backfill-in-reverse needed; data is
    observability/ephemeral, not authoritative state).
"""


def up(db) -> None:
    """Create agent_envelopes collection with required indexes."""
    if "agent_envelopes" not in db.list_collection_names():
        db.create_collection("agent_envelopes")
    col = db["agent_envelopes"]
    col.create_index([("task_id", 1)], name="task_id_1")
    col.create_index(
        [("source_envelope_id", 1)],
        name="source_envelope_id_1",
        sparse=True,  # most envelopes have no parent; sparse avoids nulls bloating index
    )
    col.create_index(
        [("agent_id", 1), ("timestamp", -1)],
        name="agent_id_1_timestamp_-1",
    )
    col.create_index([("timestamp", -1)], name="timestamp_-1")


def down(db) -> None:
    """Drop agent_envelopes collection."""
    if "agent_envelopes" in db.list_collection_names():
        db["agent_envelopes"].drop()
