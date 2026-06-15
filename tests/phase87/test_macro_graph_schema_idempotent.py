"""Wave 0 idempotency — second migration run is a no-op.

Plan 87-02 OVERVIEW acceptance: re-applying the migration on an already-
migrated database produces zero new constraints/indexes (count delta = 0).
This is what makes the migration safe to run on every dev Neo4j boot.

Per project lock: no env defaults; testcontainers fixture supplies the URL.
"""
import pathlib

import pytest

pytestmark = pytest.mark.phase_87

MIGRATION_PATH = (
    pathlib.Path(__file__).parent.parent.parent.parent
    / "vm105" / "migrations" / "0087_macro_graph_schema.cypher"
)


def _count_macro_constraints_indexes(session):
    constraints = session.run(
        "SHOW CONSTRAINTS WHERE name STARTS WITH 'macro_' OR name STARTS WITH 'asset_'"
    ).data()
    indexes = session.run(
        "SHOW INDEXES WHERE name STARTS WITH 'macro_' OR name STARTS WITH 'asset_'"
    ).data()
    return len(constraints), len(indexes)


def test_second_application_is_noop(neo4j_test_driver):
    """Re-applying the migration must NOT raise and must NOT add constraints/indexes."""
    assert MIGRATION_PATH.exists(), f"Migration file missing: {MIGRATION_PATH}"
    cypher_text = MIGRATION_PATH.read_text()
    with neo4j_test_driver.session() as session:
        before_constraints, before_indexes = _count_macro_constraints_indexes(session)

        # Apply migration again, statement by statement (mirror conftest pattern).
        for stmt in [s.strip() for s in cypher_text.split(";\n") if s.strip()]:
            # Strip Cypher comments and blank lines from each statement.
            stripped = "\n".join(
                line for line in stmt.splitlines()
                if line.strip() and not line.strip().startswith("//")
            )
            if stripped:
                session.run(stripped)

        after_constraints, after_indexes = _count_macro_constraints_indexes(session)

    assert before_constraints == after_constraints, (
        f"Idempotency broken: constraints {before_constraints} -> {after_constraints}"
    )
    assert before_indexes == after_indexes, (
        f"Idempotency broken: indexes {before_indexes} -> {after_indexes}"
    )
    assert before_constraints == 2  # macro_indicator_id_unique + asset_symbol_unique
    assert before_indexes == 4      # 2 constraint-backed + 2 relationship-property
