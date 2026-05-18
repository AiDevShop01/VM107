"""Migration 014: Create refinement_loops collection + 4 indexes.

Phase 48 Plan 48-02 Task 2.1 — RefinementLoopState persistence substrate.

Collection: refinement_loops
Schema: fingpt_core.contracts.schemas.RefinementLoopState (Phase 48 Plan 01)

Indexes created (per CONTEXT.md § Decision 3 + Plan 48-02 frontmatter):
  - loop_id_1                                  unique
  - root_hypothesis_id_1_started_at_-1          compound for "all loops for a hypothesis, newest first"
  - termination_reason_1_updated_at_-1          compound for telemetry / failure mining
  - task_id_1                                   unique (task scheduler join key — CONTEXT § Decision 17)

WORM enforcement lives at the registry-tag level (worm: true in
VM107/registry/collection/refinement_loops.yaml). MongoDB has no native WORM;
application-layer + collection-registry tag form the enforcement contract.

Idempotent: up() can run twice safely; existing indexes are skipped.
down() drops only the 4 indexes this migration created (collection preserved).

Pattern: mirrors migration 009_journal_id_field.py (Phase 47).
"""
import logging

log = logging.getLogger(__name__)

COLLECTION = "refinement_loops"

# (key_list, kwargs) tuples — kwargs MUST include name= so we can identify our own
# indexes for idempotent skip and clean down().
INDEXES: list[tuple[list[tuple[str, int]], dict]] = [
    ([("loop_id", 1)], {"name": "loop_id_1", "unique": True}),
    (
        [("root_hypothesis_id", 1), ("started_at", -1)],
        {"name": "root_hypothesis_id_1_started_at_-1"},
    ),
    (
        [("termination_reason", 1), ("updated_at", -1)],
        {"name": "termination_reason_1_updated_at_-1"},
    ),
    ([("task_id", 1)], {"name": "task_id_1", "unique": True, "sparse": True}),
]

_INDEX_NAMES = {kwargs["name"] for _, kwargs in INDEXES}


def up(db) -> None:
    """Create refinement_loops collection (if absent) + 4 indexes (if absent).

    Idempotent: skips indexes that already exist.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        db.create_collection(COLLECTION)
        log.info("Migration 014: created collection %s", COLLECTION)

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}

    for keys, kwargs in INDEXES:
        name = kwargs["name"]
        if name in existing:
            log.info("Migration 014: index %s already exists; skipping", name)
            continue
        col.create_index(keys, **kwargs)
        log.info("Migration 014: created index %s on %s", name, COLLECTION)


def down(db) -> None:
    """Drop the 4 indexes this migration added. Collection preserved.

    Idempotent: skips indexes that are already missing.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        log.info("Migration 014: collection %s missing; nothing to drop", COLLECTION)
        return

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}

    for name in _INDEX_NAMES:
        if name not in existing:
            log.info("Migration 014: index %s missing; skipping drop", name)
            continue
        col.drop_index(name)
        log.info("Migration 014: dropped index %s from %s", name, COLLECTION)
