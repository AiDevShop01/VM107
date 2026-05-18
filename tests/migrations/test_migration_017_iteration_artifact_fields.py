"""Phase 48 Plan 48-02 Task 2.2 — REQ-48-D13.

Tests migration 017 (iteration-artifact stamping — FIELD-ADDITIVE index only):
  - For each of {agent_envelopes, code_modules, build_reports, backtest_results,
    critic_verdicts} (only those that exist), up() adds a compound index on
    (refinement_loop_id ASC, iteration_number ASC).
  - up() does NOT backfill existing documents (fields populated going forward only).
  - up() does NOT create new collections (additive only — except that critic_verdicts
    is created by migration 018; this migration is order-tolerant).
  - up() idempotent.
  - down() drops only the new indexes.

Uses mongomock for in-memory MongoDB simulation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import mongomock
import pytest


def _load_migration():
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    path = repo_root / "core" / "migrations" / "scripts" / "017_iteration_artifact_fields.py"
    spec = importlib.util.spec_from_file_location("migration_017", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration_017 = _load_migration()


INDEX_NAME = "refinement_loop_id_1_iteration_number_1"

# Collections the migration considers — Plan 48-02 § Task 2.2 frontmatter list.
TARGET_COLLECTIONS = [
    "agent_envelopes",
    "code_modules",
    "build_reports",
    "backtest_results",
    "critic_verdicts",
]


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    return client["fingpt_agents"]


def _index_names(db, collection: str) -> set[str]:
    return {idx["name"] for idx in db[collection].list_indexes()}


def _seed_collections(db, names: list[str]) -> None:
    for n in names:
        if n not in db.list_collection_names():
            db.create_collection(n)


def test_up_adds_index_to_existing_collections(db):
    """When ALL 5 target collections exist, up() creates the index on all 5."""
    _seed_collections(db, TARGET_COLLECTIONS)
    migration_017.up(db)
    for c in TARGET_COLLECTIONS:
        assert INDEX_NAME in _index_names(db, c), f"missing index on {c}"


def test_up_skips_missing_collections(db):
    """When critic_verdicts does NOT exist (migration 018 not yet run), up()
    must skip it without raising."""
    _seed_collections(db, ["agent_envelopes", "code_modules", "build_reports", "backtest_results"])
    # critic_verdicts intentionally absent.
    migration_017.up(db)
    # 4 stamped:
    for c in ["agent_envelopes", "code_modules", "build_reports", "backtest_results"]:
        assert INDEX_NAME in _index_names(db, c)
    # critic_verdicts NOT auto-created:
    assert "critic_verdicts" not in db.list_collection_names()


def test_up_does_not_backfill_documents(db):
    """Existing documents are not mutated (no field backfill)."""
    _seed_collections(db, ["agent_envelopes"])
    db["agent_envelopes"].insert_one({"_id": "env_1", "agent_id": "x", "timestamp": "t"})
    migration_017.up(db)
    doc = db["agent_envelopes"].find_one({"_id": "env_1"})
    # Migration must not have added fields to existing docs.
    assert "refinement_loop_id" not in doc
    assert "iteration_number" not in doc


def test_up_is_idempotent(db):
    _seed_collections(db, TARGET_COLLECTIONS)
    migration_017.up(db)
    first = {c: _index_names(db, c) for c in TARGET_COLLECTIONS}
    migration_017.up(db)
    second = {c: _index_names(db, c) for c in TARGET_COLLECTIONS}
    assert first == second


def test_down_drops_only_migration_indexes(db):
    _seed_collections(db, TARGET_COLLECTIONS)
    migration_017.up(db)
    migration_017.down(db)
    for c in TARGET_COLLECTIONS:
        assert INDEX_NAME not in _index_names(db, c)


def test_down_is_idempotent(db):
    _seed_collections(db, TARGET_COLLECTIONS)
    migration_017.up(db)
    migration_017.down(db)
    migration_017.down(db)


def test_down_tolerates_missing_collections(db):
    """down() must not raise if a target collection was never created."""
    _seed_collections(db, ["agent_envelopes"])  # only one
    migration_017.up(db)
    migration_017.down(db)  # must not raise
