"""Migration 017: Stamp iteration-artifact collections with compound index.

Phase 48 Plan 48-02 Task 2.2 — Per-iteration artifact correlation
(CONTEXT § Decision 13).

This migration is FIELD-ADDITIVE only — it does NOT create new collections and
does NOT backfill existing documents. Phase 48 iteration-stamp fields
(`iteration_number`, `parent_iteration`, `refinement_delta_id`,
`refinement_loop_id`, `root_hypothesis_id`, `registry_snapshot_hash`) are
populated on documents written going forward (Plan 48-03+ orchestrator stamps
them at persistence time).

The migration's job is to make the loop-correlation query
``WHERE refinement_loop_id = X AND iteration_number = N`` fast — without it,
Plan 48-03+ would do collection scans on every iteration replay.

For each of the 5 iteration-artifact collections that EXISTS in the database,
adds the compound index:
  - refinement_loop_id_1_iteration_number_1   (ASC, ASC)

Target collections (Plan 48-02 frontmatter):
  - agent_envelopes      (Phase 44 — exists)
  - code_modules         (Phase 45 — may not exist until Plan 48-03)
  - build_reports        (Phase 48 Plan 01 wrapper return type — may not exist)
  - backtest_results     (Phase 45 — may not exist)
  - critic_verdicts      (created by migration 018 — order-tolerant)

Order tolerance:
  If 017 runs before 018 (alphabetical), critic_verdicts is absent and we skip it.
  If 017 runs after 018, critic_verdicts exists and gets the index.
  Both orderings are valid; both produce the same final state when both
  migrations have run.

Idempotent: skips collections that don't exist and indexes that already exist.

Pattern: mirrors migration 014/015/016 idempotency pattern; differs by iterating
over a list of target collections instead of one.
"""
import logging

log = logging.getLogger(__name__)

# Collections that may carry per-iteration artifacts (CONTEXT § Decision 13).
TARGET_COLLECTIONS = [
    "agent_envelopes",
    "code_modules",
    "build_reports",
    "backtest_results",
    "critic_verdicts",
]

INDEX_KEYS = [("refinement_loop_id", 1), ("iteration_number", 1)]
INDEX_NAME = "refinement_loop_id_1_iteration_number_1"


def up(db) -> None:
    """Add the (refinement_loop_id, iteration_number) compound index to each
    target collection that exists. No collections created, no documents
    mutated.

    Idempotent: skips collections that are absent and indexes that already exist.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    existing_collections = set(db.list_collection_names())

    for col_name in TARGET_COLLECTIONS:
        if col_name not in existing_collections:
            log.info(
                "Migration 017: collection %s missing; skipping (additive only)",
                col_name,
            )
            continue

        col = db[col_name]
        existing_indexes = {idx["name"] for idx in col.list_indexes()}
        if INDEX_NAME in existing_indexes:
            log.info(
                "Migration 017: index %s already exists on %s; skipping",
                INDEX_NAME,
                col_name,
            )
            continue
        col.create_index(INDEX_KEYS, name=INDEX_NAME)
        log.info("Migration 017: created index %s on %s", INDEX_NAME, col_name)


def down(db) -> None:
    """Drop the (refinement_loop_id, iteration_number) index from each target
    collection where it exists. Collections preserved.

    Idempotent.

    Args:
        db: pymongo.Database handle pointing to the fingpt_agents database.
    """
    existing_collections = set(db.list_collection_names())

    for col_name in TARGET_COLLECTIONS:
        if col_name not in existing_collections:
            log.info("Migration 017: collection %s missing; nothing to drop", col_name)
            continue

        col = db[col_name]
        existing_indexes = {idx["name"] for idx in col.list_indexes()}
        if INDEX_NAME not in existing_indexes:
            log.info(
                "Migration 017: index %s absent on %s; skipping drop",
                INDEX_NAME,
                col_name,
            )
            continue
        col.drop_index(INDEX_NAME)
        log.info("Migration 017: dropped index %s from %s", INDEX_NAME, col_name)
