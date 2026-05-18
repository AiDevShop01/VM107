"""Migration 018: Create critic_verdicts collection + 1 unique compound index.

Phase 48 Plan 48-02 Task 2.2 — Explicit critic-verdict collection so
Plan 48-03 `persist_atomically` can rely on it existing.

Collection: critic_verdicts (WORM — append-only, one verdict per loop per iteration)
Schema: fingpt_core.contracts.schemas.CriticVerdict (Phase 48 Plan 01).

Index created:
  - loop_id_1_iteration_number_1     UNIQUE compound — at most one CriticVerdict
                                     per (loop, iteration). Enforces
                                     CONTEXT § Decision 13 "one verdict per iteration".

WORM enforcement lives at the registry-tag level
(VM107/registry/collection/critic_verdicts.yaml — worm: true).

Idempotent: up() can run twice; collection skipped if present, index skipped
if present. down() drops only the index; collection preserved.

Pattern: mirrors migration 014_refinement_loops.py.
"""
import logging

log = logging.getLogger(__name__)

COLLECTION = "critic_verdicts"
INDEX_KEYS = [("loop_id", 1), ("iteration_number", 1)]
INDEX_NAME = "loop_id_1_iteration_number_1"


def up(db) -> None:
    """Create critic_verdicts collection (if absent) + unique compound index
    (if absent).

    Idempotent.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        db.create_collection(COLLECTION)
        log.info("Migration 018: created collection %s", COLLECTION)
    else:
        log.info("Migration 018: collection %s already exists; skipping create", COLLECTION)

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}
    if INDEX_NAME in existing:
        log.info("Migration 018: index %s already exists; skipping", INDEX_NAME)
        return

    col.create_index(INDEX_KEYS, name=INDEX_NAME, unique=True)
    log.info("Migration 018: created unique index %s on %s", INDEX_NAME, COLLECTION)


def down(db) -> None:
    """Drop the loop_id+iteration_number index. Collection preserved.

    Idempotent.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        log.info("Migration 018: collection %s missing; nothing to drop", COLLECTION)
        return

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}
    if INDEX_NAME not in existing:
        log.info("Migration 018: index %s missing; skipping drop", INDEX_NAME)
        return

    col.drop_index(INDEX_NAME)
    log.info("Migration 018: dropped index %s from %s", INDEX_NAME, COLLECTION)
