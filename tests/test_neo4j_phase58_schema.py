"""Phase 58-01 — VM107 Neo4j schema migration 010 tests.

Validates the migration script that adds :Execution + :BehavioralPattern
unique constraints and supporting indexes for the Wave 5 ExecutionNeo4jProjector.

Migration script: VM107/core/migrations/scripts/010_neo4j_phase58_schema.py

Two test tiers:
- Unit (default, no Neo4j required): static-source asserts on the migration
  module. Verifies CONSTRAINTS + INDEXES tuples, IF NOT EXISTS idempotency,
  upgrade()/downgrade() function shape, no disruption to Phase 4 (migration
  003) constraint names.
- Integration (`@pytest.mark.integration`, requires live Neo4j @ 192.168.1.105):
  applies the migration via the runner pattern and asserts constraints exist
  via SHOW CONSTRAINTS.

Plan body called the file `004_neo4j_phase58_schema.py`. Renumbered to `010_`
because `004_goal_task_system.py` already exists in this repo (Rule 1
deviation; documented in 58-01 SUMMARY).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "core" / "migrations" / "scripts" / "010_neo4j_phase58_schema.py"
)


def _load_migration():
    """Load the migration module by file path (avoid leading-digit import problem)."""
    spec = importlib.util.spec_from_file_location(
        "phase58_schema_migration", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Unit tests (default suite — no Neo4j required) ───────────────────────


def test_migration_file_exists():
    """Migration file must be present at the renumbered path."""
    assert _MIGRATION_PATH.exists(), (
        f"Migration file missing: {_MIGRATION_PATH}. "
        "Plan body said 004_neo4j_phase58_schema.py; renumbered to 010_ "
        "because 004_goal_task_system.py already exists."
    )


def test_module_loads_cleanly():
    """Migration script must import without errors (no syntax/import issues)."""
    mod = _load_migration()
    assert hasattr(mod, "CONSTRAINTS")
    assert hasattr(mod, "INDEXES")
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")


def test_constraints_table_shape():
    """CONSTRAINTS list contains exactly 2 entries: execution_id + behavioral_pattern_id."""
    mod = _load_migration()
    names = {name for name, _cypher in mod.CONSTRAINTS}
    assert names == {"execution_id_unique", "behavioral_pattern_id_unique"}, (
        f"Expected 2 named constraints; got: {names}"
    )


def test_indexes_table_shape():
    """INDEXES list contains exactly 2 entries: execution_strategy + execution_instrument."""
    mod = _load_migration()
    names = {name for name, _cypher in mod.INDEXES}
    assert names == {"execution_strategy_idx", "execution_instrument_idx"}, (
        f"Expected 2 named indexes; got: {names}"
    )


def test_constraints_use_if_not_exists_idempotency():
    """Every CREATE CONSTRAINT statement MUST use IF NOT EXISTS (idempotent re-apply)."""
    mod = _load_migration()
    for name, cypher in mod.CONSTRAINTS:
        assert "IF NOT EXISTS" in cypher, (
            f"Constraint {name} missing IF NOT EXISTS — not idempotent."
        )
        assert "CREATE CONSTRAINT" in cypher
        assert "REQUIRE" in cypher
        assert "IS UNIQUE" in cypher


def test_indexes_use_if_not_exists_idempotency():
    """Every CREATE INDEX statement MUST use IF NOT EXISTS (idempotent re-apply)."""
    mod = _load_migration()
    for name, cypher in mod.INDEXES:
        assert "IF NOT EXISTS" in cypher, (
            f"Index {name} missing IF NOT EXISTS — not idempotent."
        )
        assert "CREATE INDEX" in cypher


def test_execution_constraint_targets_e_id():
    """execution_id_unique constraint MUST target (e:Execution) REQUIRE e.id IS UNIQUE."""
    mod = _load_migration()
    for name, cypher in mod.CONSTRAINTS:
        if name == "execution_id_unique":
            assert "(e:Execution)" in cypher
            assert "e.id IS UNIQUE" in cypher
            return
    pytest.fail("execution_id_unique not found in CONSTRAINTS")


def test_behavioral_pattern_constraint_targets_b_id():
    """behavioral_pattern_id_unique MUST target (b:BehavioralPattern) REQUIRE b.id IS UNIQUE."""
    mod = _load_migration()
    for name, cypher in mod.CONSTRAINTS:
        if name == "behavioral_pattern_id_unique":
            assert "(b:BehavioralPattern)" in cypher
            assert "b.id IS UNIQUE" in cypher
            return
    pytest.fail("behavioral_pattern_id_unique not found in CONSTRAINTS")


def test_upgrade_handles_missing_neo4j_gracefully():
    """upgrade(context={}) must SKIP if no neo4j driver is provided (mirrors migration 003)."""
    mod = _load_migration()
    # Should not raise — runner pattern: print SKIP and return.
    mod.upgrade({})
    mod.upgrade({"neo4j": None})


def test_downgrade_handles_missing_neo4j_gracefully():
    """downgrade(context={}) must SKIP if no neo4j driver is provided."""
    mod = _load_migration()
    mod.downgrade({})
    mod.downgrade({"neo4j": None})


def test_does_not_disturb_phase4_constraints():
    """Migration 010 MUST NOT reference or drop migration 003's constraint names.

    Phase 4 (migration 003) constraint names that must remain in place:
        constraint_strategy_id_unique
        constraint_instrument_id_unique  (named via fstring in 003)
        constraint_regime_id_unique
        constraint_feature_id_unique
        constraint_signal_id_unique
        ...etc (14 total operational labels)

    Our new constraints use different name prefixes (no `constraint_` prefix)
    so name collision is impossible.
    """
    mod = _load_migration()
    src = _MIGRATION_PATH.read_text()

    phase4_constraint_names = (
        "constraint_strategy_id_unique",
        "constraint_instrument_id_unique",
        "constraint_regime_id_unique",
        "constraint_feature_id_unique",
        "constraint_signal_id_unique",
        "constraint_agent_id_unique",
        "constraint_tool_id_unique",
        "constraint_task_id_unique",
        "constraint_dataset_id_unique",
        "constraint_validationrun_id_unique",
        "constraint_session_id_unique",
        "constraint_instrumentprofile_id_unique",
    )
    for legacy_name in phase4_constraint_names:
        assert legacy_name not in src, (
            f"Migration 010 references legacy constraint name '{legacy_name}' — "
            "must not modify Phase 4 schema."
        )

    # Sanity: our new constraint names are distinct from the legacy ones
    new_names = {name for name, _ in mod.CONSTRAINTS}
    assert new_names.isdisjoint(set(phase4_constraint_names))


def test_runner_signature_compatibility():
    """upgrade() + downgrade() take a single context dict argument (runner contract)."""
    import inspect

    mod = _load_migration()

    upgrade_sig = inspect.signature(mod.upgrade)
    downgrade_sig = inspect.signature(mod.downgrade)

    assert list(upgrade_sig.parameters) == ["context"], (
        f"upgrade() signature mismatch: {upgrade_sig}"
    )
    assert list(downgrade_sig.parameters) == ["context"], (
        f"downgrade() signature mismatch: {downgrade_sig}"
    )


# ── Integration tests (require live Neo4j @ 192.168.1.105) ───────────────


@pytest.mark.integration
def test_constraints_exist_after_apply():
    """After upgrade(), SHOW CONSTRAINTS must return both new constraint names."""
    pytest.importorskip("neo4j", reason="neo4j driver not installed in this venv.")
    import os

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://192.168.1.105:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD not set; skipping integration test.")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        mod = _load_migration()
        mod.upgrade({"neo4j": driver})

        with driver.session() as session:
            result = session.run("SHOW CONSTRAINTS")
            names = {row["name"] for row in result.data()}
            assert "execution_id_unique" in names
            assert "behavioral_pattern_id_unique" in names
            # Phase 4 constraints still in place (no disruption)
            assert "constraint_strategy_id_unique" in names
            assert "constraint_instrument_id_unique" in names
            assert "constraint_regime_id_unique" in names
    finally:
        driver.close()


@pytest.mark.integration
def test_idempotent_apply():
    """Running upgrade() twice must NOT raise (IF NOT EXISTS clause)."""
    pytest.importorskip("neo4j", reason="neo4j driver not installed in this venv.")
    import os

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://192.168.1.105:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD not set; skipping integration test.")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        mod = _load_migration()
        mod.upgrade({"neo4j": driver})
        mod.upgrade({"neo4j": driver})  # second call must not raise
    finally:
        driver.close()


@pytest.mark.integration
def test_execution_constraint_blocks_duplicates():
    """After upgrade(), CREATE (:Execution {id: 'X'}) twice must raise on second insert."""
    pytest.importorskip("neo4j", reason="neo4j driver not installed in this venv.")
    import os
    from uuid import uuid4

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://192.168.1.105:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD not set; skipping integration test.")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    test_id = f"test-{uuid4()}"
    try:
        mod = _load_migration()
        mod.upgrade({"neo4j": driver})

        with driver.session() as session:
            session.run(
                "CREATE (:Execution {id: $id})", id=test_id
            )
            with pytest.raises(Exception, match="ConstraintValidationFailed|already exists"):
                session.run(
                    "CREATE (:Execution {id: $id})", id=test_id
                )
            # cleanup
            session.run("MATCH (e:Execution {id: $id}) DETACH DELETE e", id=test_id)
    finally:
        driver.close()


@pytest.mark.integration
def test_behavioral_pattern_constraint_blocks_duplicates():
    """After upgrade(), CREATE (:BehavioralPattern {id: 'hesitation'}) twice must raise."""
    pytest.importorskip("neo4j", reason="neo4j driver not installed in this venv.")
    import os

    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://192.168.1.105:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        pytest.skip("NEO4J_PASSWORD not set; skipping integration test.")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    test_id = "test_pattern_phase58"
    try:
        mod = _load_migration()
        mod.upgrade({"neo4j": driver})

        with driver.session() as session:
            session.run(
                "CREATE (:BehavioralPattern {id: $id})", id=test_id
            )
            with pytest.raises(Exception, match="ConstraintValidationFailed|already exists"):
                session.run(
                    "CREATE (:BehavioralPattern {id: $id})", id=test_id
                )
            # cleanup
            session.run(
                "MATCH (b:BehavioralPattern {id: $id}) DETACH DELETE b", id=test_id
            )
    finally:
        driver.close()
