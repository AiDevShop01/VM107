"""Phase 48 Plan 48-02 Task 2.2 — REQ-48-D1.

Tests migration 018 (critic_verdicts collection):
  - up() creates critic_verdicts via db.create_collection() if absent
  - up() ensures unique compound index on (loop_id ASC, iteration_number ASC)
  - up() idempotent (existing collection + index skipped)
  - down() drops only this migration's index

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
    path = repo_root / "core" / "migrations" / "scripts" / "018_critic_verdicts.py"
    spec = importlib.util.spec_from_file_location("migration_018", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration_018 = _load_migration()


INDEX_NAME = "loop_id_1_iteration_number_1"


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    return client["fingpt_agents"]


def _index_names(db, collection: str) -> set[str]:
    return {idx["name"] for idx in db[collection].list_indexes()}


def test_up_creates_collection_when_absent(db):
    assert "critic_verdicts" not in db.list_collection_names()
    migration_018.up(db)
    assert "critic_verdicts" in db.list_collection_names()


def test_up_creates_unique_index(db):
    migration_018.up(db)
    by_name = {idx["name"]: idx for idx in db["critic_verdicts"].list_indexes()}
    assert INDEX_NAME in by_name
    assert by_name[INDEX_NAME].get("unique", False) is True


def test_up_skips_when_collection_already_exists(db):
    db.create_collection("critic_verdicts")
    db["critic_verdicts"].insert_one({"_id": "v1", "loop_id": "L1", "iteration_number": 0})
    migration_018.up(db)
    # Pre-existing doc preserved:
    assert db["critic_verdicts"].count_documents({"_id": "v1"}) == 1
    assert INDEX_NAME in _index_names(db, "critic_verdicts")


def test_up_is_idempotent(db):
    migration_018.up(db)
    a = _index_names(db, "critic_verdicts")
    migration_018.up(db)
    b = _index_names(db, "critic_verdicts")
    assert a == b


def test_down_drops_index(db):
    migration_018.up(db)
    migration_018.down(db)
    assert INDEX_NAME not in _index_names(db, "critic_verdicts")


def test_down_is_idempotent(db):
    migration_018.up(db)
    migration_018.down(db)
    migration_018.down(db)


def test_round_trip(db):
    migration_018.up(db)
    migration_018.down(db)
    migration_018.up(db)
    assert INDEX_NAME in _index_names(db, "critic_verdicts")
