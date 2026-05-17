"""Phase 47.6 LD-9 + LD-10: backfill registry_snapshot_hash on pre-47.6 agent_envelopes.

This migration is one-way (LD-9 epistemic epoch invariant — irreversible).
Post-migration, NOT NULL is enforced at the Pydantic layer (no Mongo schema-level
NOT NULL exists in MongoDB). Use read_envelope_tolerant() for backward compat reads.

Three-step migration:
  1. Schema-add: add the field conceptually (MongoDB is schemaless; this is a no-op at DB level)
  2. Sentinel backfill: fill NULL/missing registry_snapshot_hash with REGISTRY_SNAPSHOT_PRE_47_6
  3. App-layer NOT NULL: enforced by CapabilityProvenanceMixin in AgentEnvelope (see 47.6-04)

Idempotent: re-running on already-stamped docs is a no-op (update_many only
matches docs where the field is missing or null).

Post-condition check: asserts 0 docs remain with null/missing registry_snapshot_hash.

SENTINEL IMPORT:
    Never hardcode "pre-47.6" as a string literal. Always import from:
    fingpt_core.contracts.capability_registry.constants.REGISTRY_SNAPSHOT_PRE_47_6
"""

import logging
from datetime import datetime, timezone

from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6

log = logging.getLogger(__name__)

# Timestamp used for pre-47.6 documents that have no generated_at value.
# This marks the epoch boundary — documents from before Phase 47.6 deployment.
DEPLOY_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)

_COLLECTION = "agent_envelopes"
_MIGRATION_ID = "011_47_6_stamping_agent_envelopes"


def up(db) -> None:
    """Backfill registry_snapshot_hash on pre-47.6 agent_envelopes.

    Idempotent: docs already stamped are skipped by the $or filter.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    col = db[_COLLECTION]

    # Build the idempotency-tracking collection entry (separate from the migration runner)
    # so we can skip if already run.
    applied_col = db["migrations_47_6"]
    already_applied = applied_col.find_one({"_id": _MIGRATION_ID})
    if already_applied:
        log.info("Migration %s already applied — skipping", _MIGRATION_ID)
        return

    result = col.update_many(
        {
            "$or": [
                {"registry_snapshot_hash": {"$exists": False}},
                {"registry_snapshot_hash": None},
            ]
        },
        {
            "$set": {
                "registry_snapshot_hash": REGISTRY_SNAPSHOT_PRE_47_6,
                "registry_snapshot_generated_at": DEPLOY_TS,
                "registry_schema_version": "0.0",
                # Plan 06 fields — pre-populated empty lists for forward compatibility
                "capability_introspection_log": [],
                "capability_refusal_log": [],
            }
        },
    )
    log.info(
        "Migration %s: %s agent_envelopes backfilled with sentinel",
        _MIGRATION_ID,
        result.modified_count,
    )

    # Post-condition smoke check (Mongo has no NOT NULL — app-layer enforces via Pydantic)
    remaining = col.count_documents(
        {"registry_snapshot_hash": {"$in": [None, ""]}}
    )
    assert remaining == 0, (
        f"Backfill incomplete: {remaining} agent_envelopes still have null/empty "
        f"registry_snapshot_hash after migration {_MIGRATION_ID}"
    )

    # Record migration as applied (idempotency tracking)
    applied_col.insert_one({
        "_id": _MIGRATION_ID,
        "applied_at": datetime.now(timezone.utc),
        "modified_count": result.modified_count,
    })


def down(db) -> None:
    """This migration is IRREVERSIBLE per LD-9 (epistemic epochs are one-way).

    Raises:
        RuntimeError: Always — this migration cannot be reversed.
    """
    raise RuntimeError(
        f"Phase 47.6 sentinel backfill is one-way. "
        f"See CONTEXT.md decision #9 (LD-9 epistemic epoch invariant). "
        f"Migration: {_MIGRATION_ID}"
    )
