"""Migration 015: Create accepted_strategies collection + 3 indexes.

Phase 48 Plan 48-02 Task 2.2 — Promoted operational cognition substrate.

Collection: accepted_strategies (WORM — once written, immutable)
Schema: see CONTEXT.md § Decision 11. Doc shape pinned there; registry YAML at
        VM107/registry/collection/accepted_strategies.yaml points to the Pydantic
        contract (TBD by Plan 08a when the accepted-strategy emitter ships).

Indexes created (per Plan 48-02 frontmatter):
  - accepted_strategy_id_1                          unique
  - root_hypothesis_id_1_accepted_at_-1             compound for "all accepted strategies for a hypothesis, newest first"
  - strategy_family_1_accepted_at_-1                compound for family-level discovery

WORM enforcement lives at the registry-tag level (worm: true in
VM107/registry/collection/accepted_strategies.yaml). Mongo has no native WORM;
application-layer single-writer (Plan 08a acceptance emitter) + collection-registry
tag form the contract.

Idempotent: up() can run twice safely. down() drops only the 3 indexes this
migration created (collection preserved — Phase 47 LD-9 epistemic-epoch lock).

Pattern: mirrors migration 014_refinement_loops.py / 009_journal_id_field.py.
"""
import logging

log = logging.getLogger(__name__)

COLLECTION = "accepted_strategies"

INDEXES: list[tuple[list[tuple[str, int]], dict]] = [
    ([("accepted_strategy_id", 1)], {"name": "accepted_strategy_id_1", "unique": True}),
    (
        [("root_hypothesis_id", 1), ("accepted_at", -1)],
        {"name": "root_hypothesis_id_1_accepted_at_-1"},
    ),
    (
        [("strategy_family", 1), ("accepted_at", -1)],
        {"name": "strategy_family_1_accepted_at_-1"},
    ),
]

_INDEX_NAMES = {kwargs["name"] for _, kwargs in INDEXES}


def up(db) -> None:
    """Create accepted_strategies collection (if absent) + 3 indexes (if absent).

    Idempotent: skips collection / indexes that already exist.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        db.create_collection(COLLECTION)
        log.info("Migration 015: created collection %s", COLLECTION)

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}

    for keys, kwargs in INDEXES:
        name = kwargs["name"]
        if name in existing:
            log.info("Migration 015: index %s already exists; skipping", name)
            continue
        col.create_index(keys, **kwargs)
        log.info("Migration 015: created index %s on %s", name, COLLECTION)


def down(db) -> None:
    """Drop the 3 indexes this migration added. Collection preserved.

    Idempotent: skips indexes that are already missing.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        log.info("Migration 015: collection %s missing; nothing to drop", COLLECTION)
        return

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}

    for name in _INDEX_NAMES:
        if name not in existing:
            log.info("Migration 015: index %s missing; skipping drop", name)
            continue
        col.drop_index(name)
        log.info("Migration 015: dropped index %s from %s", name, COLLECTION)
