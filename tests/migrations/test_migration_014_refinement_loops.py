"""Phase 48 Plan 48-02 Task 2.1 — REQ-48-D3.

Tests migration 014 (refinement_loops collection):
  - up(db) creates collection with 4 indexes
  - up(db) is idempotent (second call is a no-op)
  - down(db) drops only the indexes this migration added
  - down(db) is idempotent

Uses mongomock for in-memory MongoDB simulation (no live Mongo dependency).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import mongomock
import pytest


def _load_migration():
    """Dynamically import the 014_refinement_loops migration module.

    The numeric-prefix filename is not a valid Python identifier, so we use
    importlib (same strategy as core/migrations/registry.py::_import_migration).
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[2]  # tests/migrations -> tests -> VM107
    path = repo_root / "core" / "migrations" / "scripts" / "014_refinement_loops.py"
    spec = importlib.util.spec_from_file_location("migration_014", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration_014 = _load_migration()


# Index names this migration creates (must match the migration source).
EXPECTED_INDEX_NAMES = {
    "loop_id_1",
    "root_hypothesis_id_1_started_at_-1",
    "termination_reason_1_updated_at_-1",
    "task_id_1",
}


@pytest.fixture
def db():
    """Fresh mongomock fingpt_agents DB per test."""
    client = mongomock.MongoClient()
    return client["fingpt_agents"]


def _index_names(db, collection: str) -> set[str]:
    return {idx["name"] for idx in db[collection].list_indexes()}


def test_up_creates_collection_with_4_indexes(db):
    """After up(), refinement_loops exists with all 4 required indexes."""
    migration_014.up(db)

    assert "refinement_loops" in db.list_collection_names()
    names = _index_names(db, "refinement_loops")
    # _id_ is always present in MongoDB; the 4 we add are the migration's contract.
    assert EXPECTED_INDEX_NAMES.issubset(names), (
        f"missing indexes: {EXPECTED_INDEX_NAMES - names}"
    )


def test_up_is_idempotent(db):
    """Calling up() twice must not raise and final state must be identical."""
    migration_014.up(db)
    names_after_first = _index_names(db, "refinement_loops")
    migration_014.up(db)
    names_after_second = _index_names(db, "refinement_loops")
    assert names_after_first == names_after_second


def test_loop_id_index_is_unique(db):
    """loop_id_1 must be a unique index (CONTEXT § Decision 3)."""
    migration_014.up(db)
    by_name = {idx["name"]: idx for idx in db["refinement_loops"].list_indexes()}
    assert by_name["loop_id_1"].get("unique", False) is True


def test_task_id_index_is_unique(db):
    """task_id_1 must be a unique index (sparse permitted — task_id may be None)."""
    migration_014.up(db)
    by_name = {idx["name"]: idx for idx in db["refinement_loops"].list_indexes()}
    assert by_name["task_id_1"].get("unique", False) is True


def test_down_drops_only_migration_indexes(db):
    """down() removes the 4 indexes this migration added; collection remains."""
    migration_014.up(db)
    migration_014.down(db)

    # Collection itself stays (data preservation principle — drop indexes, not data).
    # Even if collection was created by this migration with no data, we leave it.
    remaining = _index_names(db, "refinement_loops")
    # _id_ index always remains; none of our 4 named indexes should be present.
    assert remaining.isdisjoint(EXPECTED_INDEX_NAMES), (
        f"down() left indexes behind: {remaining & EXPECTED_INDEX_NAMES}"
    )


def test_down_is_idempotent(db):
    """down() called twice must not raise."""
    migration_014.up(db)
    migration_014.down(db)
    migration_014.down(db)  # second call: no-op


def test_up_down_round_trip(db):
    """up → down → up restores the original 4 indexes."""
    migration_014.up(db)
    migration_014.down(db)
    migration_014.up(db)
    names = _index_names(db, "refinement_loops")
    assert EXPECTED_INDEX_NAMES.issubset(names)
