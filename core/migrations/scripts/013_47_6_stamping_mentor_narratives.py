"""Phase 47.6 LD-9 + LD-10: backfill registry_snapshot_hash on pre-47.6 mentor_narratives.

Same three-step pattern as migration 011 (agent_envelopes), scoped to the
mentor_narratives collection (Mongo half of the mentor narrative surface).

Scope clarification (Plan 04 vs Plan 05):
  - This migration (Plan 04) owns the Mongo mentor_narratives collection.
  - Plan 05 owns the Postgres review_narrative table (B3 fix).
  Both together complete LD-10's "Mentor narratives (Mongo + Postgres references)".

Note: mentor_narratives does NOT carry capability_introspection_log or
capability_refusal_log — those are agent_envelopes-scoped (Plan 06).

This migration is one-way (LD-9 epistemic epoch invariant — irreversible).
Idempotent: re-running on already-stamped docs is a no-op.

SENTINEL IMPORT:
    Never hardcode "pre-47.6" as a string literal. Always import from:
    fingpt_core.contracts.capability_registry.constants.REGISTRY_SNAPSHOT_PRE_47_6
"""

import logging
from datetime import datetime, timezone

from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6

log = logging.getLogger(__name__)

DEPLOY_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)

_COLLECTION = "mentor_narratives"
_MIGRATION_ID = "013_47_6_stamping_mentor_narratives"


def up(db) -> None:
    """Backfill registry_snapshot_hash on pre-47.6 mentor_narratives.

    Idempotent: docs already stamped are skipped by the $or filter.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    col = db[_COLLECTION]

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
                # NOTE: mentor_narratives does NOT carry introspection/refusal log fields.
                # Those are agent_envelopes-scoped (Plan 06). Do NOT add them here.
            }
        },
    )
    log.info(
        "Migration %s: %s mentor_narratives backfilled with sentinel",
        _MIGRATION_ID,
        result.modified_count,
    )

    remaining = col.count_documents(
        {"registry_snapshot_hash": {"$in": [None, ""]}}
    )
    assert remaining == 0, (
        f"Backfill incomplete: {remaining} mentor_narratives still have null/empty "
        f"registry_snapshot_hash after migration {_MIGRATION_ID}"
    )

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
