"""Migration 016: Create rejected_strategies collection + 5 indexes.

Phase 48 Plan 48-02 Task 2.2 — Research-failure memory substrate.

Collection: rejected_strategies (WORM — append-only failure cognition)
Schema: see CONTEXT.md § Decision 12. Rejected strategies are first-class
        research-failure cognition artifacts; the doc shape is pinned in
        CONTEXT.md and the registry YAML at
        VM107/registry/collection/rejected_strategies.yaml notes
        worm: true (no Pydantic contract published until Plan 08a emitter ships).

Indexes created (per CONTEXT § Decision 12 + Plan 48-02 frontmatter):
  - rejected_strategy_id_1        unique
  - root_hypothesis_id_1          for "all rejections for a hypothesis"
  - termination_reason_1          for failure-mode mining
  - strategy_family_1             for family-level failure analysis
  - rejected_at_-1                for time-ordered audit

WORM enforcement lives at the registry-tag level. Mongo has no native WORM;
application-layer single-writer + collection-registry tag form the contract.

Note: rejected_strategies has NO registry/strategy/<id>.yaml fan-out
(rejected ≠ capability — CONTEXT § Decision 12).

Idempotent: up() can run twice safely. down() drops only the 5 indexes this
migration created.

Pattern: mirrors migration 014_refinement_loops.py / 015_accepted_strategies.py.
"""
import logging

log = logging.getLogger(__name__)

COLLECTION = "rejected_strategies"

INDEXES: list[tuple[list[tuple[str, int]], dict]] = [
    ([("rejected_strategy_id", 1)], {"name": "rejected_strategy_id_1", "unique": True}),
    ([("root_hypothesis_id", 1)], {"name": "root_hypothesis_id_1"}),
    ([("termination_reason", 1)], {"name": "termination_reason_1"}),
    ([("strategy_family", 1)], {"name": "strategy_family_1"}),
    ([("rejected_at", -1)], {"name": "rejected_at_-1"}),
]

_INDEX_NAMES = {kwargs["name"] for _, kwargs in INDEXES}


def up(db) -> None:
    """Create rejected_strategies collection (if absent) + 5 indexes (if absent).

    Idempotent.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        db.create_collection(COLLECTION)
        log.info("Migration 016: created collection %s", COLLECTION)

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}

    for keys, kwargs in INDEXES:
        name = kwargs["name"]
        if name in existing:
            log.info("Migration 016: index %s already exists; skipping", name)
            continue
        col.create_index(keys, **kwargs)
        log.info("Migration 016: created index %s on %s", name, COLLECTION)


def down(db) -> None:
    """Drop the 5 indexes this migration added. Collection preserved.

    Idempotent.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    if COLLECTION not in db.list_collection_names():
        log.info("Migration 016: collection %s missing; nothing to drop", COLLECTION)
        return

    col = db[COLLECTION]
    existing = {idx["name"] for idx in col.list_indexes()}

    for name in _INDEX_NAMES:
        if name not in existing:
            log.info("Migration 016: index %s missing; skipping drop", name)
            continue
        col.drop_index(name)
        log.info("Migration 016: dropped index %s from %s", name, COLLECTION)
