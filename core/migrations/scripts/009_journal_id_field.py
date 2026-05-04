"""Migration 009: Add sparse compound index on agent_envelopes for journal_id chat queries.

Phase 47 Wave 1: Pre-Trade AI Assistant. journal_id is set only on chat envelopes
(NULL for Phase 44 Idea/Strategy invocation envelopes), so the index is sparse.
The Pydantic schema change (adding journal_id: Optional[str] = None to AgentEnvelope)
is code-only and lives in the commit alongside this migration.

Note on numbering: Slot 008 is reserved by Phase 45 CONTEXT.md as `008_code_modules.py`
even though Phase 45 has not yet shipped. Phase 47 uses 009 to avoid collision.
"""
import logging

log = logging.getLogger(__name__)

INDEX_NAME = "journal_id_1_timestamp_-1"


def up(db) -> None:
    """Create sparse compound index {journal_id: 1, timestamp: -1} on agent_envelopes."""
    col = db["agent_envelopes"]
    existing = {idx["name"] for idx in col.list_indexes()}
    if INDEX_NAME in existing:
        log.info("Migration 009: index %s already exists; skipping", INDEX_NAME)
        return
    col.create_index(
        [("journal_id", 1), ("timestamp", -1)],
        name=INDEX_NAME,
        sparse=True,
    )
    log.info("Migration 009: created sparse index %s", INDEX_NAME)


def down(db) -> None:
    """Drop sparse compound index journal_id_1_timestamp_-1 from agent_envelopes."""
    col = db["agent_envelopes"]
    existing = {idx["name"] for idx in col.list_indexes()}
    if INDEX_NAME not in existing:
        log.info("Migration 009: index %s missing; skipping drop", INDEX_NAME)
        return
    col.drop_index(INDEX_NAME)
    log.info("Migration 009: dropped index %s", INDEX_NAME)
