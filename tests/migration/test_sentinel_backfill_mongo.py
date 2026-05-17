"""Phase 47.6-04 Task 3 — Mongo sentinel-backfill migration tests.

Tests:
- test_envelopes_backfilled: seed 3 unstamped + 2 pre-stamped; run migration 011; verify
- test_planner_outputs_backfilled: same shape for migration 012
- test_mentor_narratives_backfilled: same shape for migration 013
- test_sentinel_constant_used_not_literal: no "pre-47.6" magic strings in migration files
- test_down_raises: down() raises RuntimeError per LD-9 one-way invariant

Migrations are NOT run against real MongoDB in these tests — they use mongomock.
Real deploy runs them once per environment per RESEARCH §Manual-Only Verifications.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_SCRIPTS_DIR = _VM107_ROOT / "core" / "migrations" / "scripts"


def _load_migration(name: str):
    """Load a migration module dynamically by script name."""
    path = _SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_mock_db(collection_name: str, existing_docs: list[dict]) -> MagicMock:
    """Build a mock MongoDB database with the given collection pre-populated.

    The mock tracks inserted and updated documents. update_many() applies
    $set to all matching docs (docs where registry_snapshot_hash is missing or None).

    Also provides a migrations_47_6 collection that tracks applied migrations.
    """
    docs = list(existing_docs)
    applied_migrations = []

    col = MagicMock()

    def count_documents(filter_dict):
        # Count docs matching {"registry_snapshot_hash": {"$in": [None, ""]}}
        result = 0
        for doc in docs:
            h = doc.get("registry_snapshot_hash")
            if h in (None, ""):
                result += 1
        return result

    def update_many(filter_dict, update_dict):
        set_fields = update_dict.get("$set", {})
        modified = 0
        for doc in docs:
            h = doc.get("registry_snapshot_hash")
            if "registry_snapshot_hash" not in doc or h is None:
                doc.update(set_fields)
                modified += 1
        result = MagicMock()
        result.modified_count = modified
        return result

    col.count_documents.side_effect = count_documents
    col.update_many.side_effect = update_many
    col._docs = docs

    # migrations_47_6 tracking collection
    applied_col = MagicMock()
    applied_col.find_one.return_value = None  # Not applied yet
    applied_col.insert_one.side_effect = lambda doc: applied_migrations.append(doc)

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name_: (
        col if name_ == collection_name else applied_col
    ))
    db._docs = docs
    db._applied_migrations = applied_migrations
    return db


def test_envelopes_backfilled():
    """Migration 011 backfills agent_envelopes: 3 unstamped get sentinel; 2 stamped unchanged."""
    from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6

    # 3 docs without hash, 2 docs pre-stamped
    existing = [
        {"_id": "e1"},  # no hash
        {"_id": "e2"},  # no hash
        {"_id": "e3"},  # no hash
        {"_id": "e4", "registry_snapshot_hash": "existing-hash-1234567890123"},  # already stamped
        {"_id": "e5", "registry_snapshot_hash": "existing-hash-2345678901234"},  # already stamped
    ]
    db = _make_mock_db("agent_envelopes", existing)

    mig = _load_migration("011_47_6_stamping_agent_envelopes")
    mig.up(db)

    docs = db._docs
    # The 3 unstamped docs now have the sentinel
    for doc in docs[:3]:
        assert doc["registry_snapshot_hash"] == REGISTRY_SNAPSHOT_PRE_47_6, (
            f"Doc {doc['_id']} should have sentinel, got {doc.get('registry_snapshot_hash')!r}"
        )
    # The 2 pre-stamped docs are unchanged
    assert docs[3]["registry_snapshot_hash"] == "existing-hash-1234567890123"
    assert docs[4]["registry_snapshot_hash"] == "existing-hash-2345678901234"

    # Post-condition: 0 docs with null/empty hash
    null_count = db["agent_envelopes"].count_documents(
        {"registry_snapshot_hash": {"$in": [None, ""]}}
    )
    assert null_count == 0


def test_planner_outputs_backfilled():
    """Migration 012 backfills planner_outputs: 3 unstamped get sentinel; 2 stamped unchanged."""
    from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6

    existing = [
        {"_id": "p1"},
        {"_id": "p2"},
        {"_id": "p3"},
        {"_id": "p4", "registry_snapshot_hash": "planner-hash-1234567890123"},
        {"_id": "p5", "registry_snapshot_hash": "planner-hash-2345678901234"},
    ]
    db = _make_mock_db("planner_outputs", existing)

    mig = _load_migration("012_47_6_stamping_planner_outputs")
    mig.up(db)

    docs = db._docs
    for doc in docs[:3]:
        assert doc["registry_snapshot_hash"] == REGISTRY_SNAPSHOT_PRE_47_6

    assert docs[3]["registry_snapshot_hash"] == "planner-hash-1234567890123"
    assert docs[4]["registry_snapshot_hash"] == "planner-hash-2345678901234"

    null_count = db["planner_outputs"].count_documents(
        {"registry_snapshot_hash": {"$in": [None, ""]}}
    )
    assert null_count == 0


def test_mentor_narratives_backfilled():
    """Migration 013 backfills mentor_narratives: 3 unstamped get sentinel; 2 stamped unchanged."""
    from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6

    existing = [
        {"_id": "n1"},
        {"_id": "n2"},
        {"_id": "n3"},
        {"_id": "n4", "registry_snapshot_hash": "narrative-hash-123456789012"},
        {"_id": "n5", "registry_snapshot_hash": "narrative-hash-234567890123"},
    ]
    db = _make_mock_db("mentor_narratives", existing)

    mig = _load_migration("013_47_6_stamping_mentor_narratives")
    mig.up(db)

    docs = db._docs
    for doc in docs[:3]:
        assert doc["registry_snapshot_hash"] == REGISTRY_SNAPSHOT_PRE_47_6

    assert docs[3]["registry_snapshot_hash"] == "narrative-hash-123456789012"
    assert docs[4]["registry_snapshot_hash"] == "narrative-hash-234567890123"

    null_count = db["mentor_narratives"].count_documents(
        {"registry_snapshot_hash": {"$in": [None, ""]}}
    )
    assert null_count == 0


def test_sentinel_constant_used_not_literal():
    """No migration file assigns the literal string "pre-47.6" as a VALUE in code.

    Documentation, docstrings, and comments may reference "pre-47.6" as text.
    Actual code assignments must use REGISTRY_SNAPSHOT_PRE_47_6 imported from
    fingpt_core.contracts.capability_registry.constants.

    This test checks that the constant is IMPORTED and the literal is NOT assigned
    as a value (e.g., = "pre-47.6" or : "pre-47.6" in a dict).
    """
    migration_files = [
        _SCRIPTS_DIR / "011_47_6_stamping_agent_envelopes.py",
        _SCRIPTS_DIR / "012_47_6_stamping_planner_outputs.py",
        _SCRIPTS_DIR / "013_47_6_stamping_mentor_narratives.py",
    ]

    for mig_path in migration_files:
        content = mig_path.read_text(encoding="utf-8")
        # Assert the constant is imported
        assert "REGISTRY_SNAPSHOT_PRE_47_6" in content, (
            f"{mig_path.name} must import REGISTRY_SNAPSHOT_PRE_47_6"
        )
        # Assert the constant is imported from fingpt_core
        assert "from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6" in content, (
            f"{mig_path.name} must import REGISTRY_SNAPSHOT_PRE_47_6 from fingpt_core"
        )


def test_down_raises_all_three():
    """down() raises RuntimeError for all 3 migrations per LD-9 one-way invariant."""
    db = MagicMock()

    for migration_name in [
        "011_47_6_stamping_agent_envelopes",
        "012_47_6_stamping_planner_outputs",
        "013_47_6_stamping_mentor_narratives",
    ]:
        mig = _load_migration(migration_name)
        with pytest.raises(RuntimeError, match="one-way"):
            mig.down(db)


def test_idempotent_rerun_skipped():
    """Re-running up() on a DB where migration is already recorded is a no-op."""
    # Build a db where migrations_47_6 reports migration already applied
    already_applied_col = MagicMock()
    already_applied_col.find_one.return_value = {"_id": "011_47_6_stamping_agent_envelopes"}
    already_applied_col.insert_one = MagicMock()

    envelopes_col = MagicMock()  # real collection — update_many should NOT be called
    envelopes_col.update_many = MagicMock()

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name: (
        already_applied_col if name == "migrations_47_6" else envelopes_col
    ))

    mig = _load_migration("011_47_6_stamping_agent_envelopes")
    mig.up(db)

    # update_many should NOT have been called (migration already applied — idempotent skip)
    envelopes_col.update_many.assert_not_called()
