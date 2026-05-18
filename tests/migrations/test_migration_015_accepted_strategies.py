"""Phase 48 Plan 48-02 Task 2.2 — REQ-48-D11.

Tests migration 015 (accepted_strategies collection):
  - up() creates accepted_strategies + 3 indexes
  - up() idempotent
  - down() drops only this migration's indexes
  - accepted_strategy_id index is unique

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
    path = repo_root / "core" / "migrations" / "scripts" / "015_accepted_strategies.py"
    spec = importlib.util.spec_from_file_location("migration_015", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration_015 = _load_migration()


EXPECTED_INDEX_NAMES = {
    "accepted_strategy_id_1",
    "root_hypothesis_id_1_accepted_at_-1",
    "strategy_family_1_accepted_at_-1",
}


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    return client["fingpt_agents"]


def _index_names(db, collection: str) -> set[str]:
    return {idx["name"] for idx in db[collection].list_indexes()}


def test_up_creates_collection_with_indexes(db):
    migration_015.up(db)
    assert "accepted_strategies" in db.list_collection_names()
    assert EXPECTED_INDEX_NAMES.issubset(_index_names(db, "accepted_strategies"))


def test_up_is_idempotent(db):
    migration_015.up(db)
    a = _index_names(db, "accepted_strategies")
    migration_015.up(db)
    b = _index_names(db, "accepted_strategies")
    assert a == b


def test_accepted_strategy_id_is_unique(db):
    migration_015.up(db)
    by_name = {idx["name"]: idx for idx in db["accepted_strategies"].list_indexes()}
    assert by_name["accepted_strategy_id_1"].get("unique", False) is True


def test_down_drops_indexes(db):
    migration_015.up(db)
    migration_015.down(db)
    remaining = _index_names(db, "accepted_strategies")
    assert remaining.isdisjoint(EXPECTED_INDEX_NAMES)


def test_down_is_idempotent(db):
    migration_015.up(db)
    migration_015.down(db)
    migration_015.down(db)


def test_round_trip(db):
    migration_015.up(db)
    migration_015.down(db)
    migration_015.up(db)
    assert EXPECTED_INDEX_NAMES.issubset(_index_names(db, "accepted_strategies"))
