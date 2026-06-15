"""Wave 0 schema validation — applies 0087 migration and asserts shape.

Plan 87-02 — applies the macro graph schema migration to a fresh Neo4j 5.15
testcontainer (via the neo4j_test_driver fixture in conftest.py) and asserts
the expected 2 constraints + 4 indexes are created with the correct names,
entity types, and properties.

Per project lock: no os.getenv defaults; testcontainers fixture supplies the URL.
"""
import pytest

pytestmark = pytest.mark.phase_87


def test_macro_constraints_created(neo4j_test_driver):
    """Two constraints named macro_* + asset_* must exist after migration."""
    with neo4j_test_driver.session() as session:
        result = session.run(
            "SHOW CONSTRAINTS WHERE name STARTS WITH 'macro_' OR name STARTS WITH 'asset_'"
        )
        names = {record["name"] for record in result}
        assert "macro_indicator_id_unique" in names
        assert "asset_symbol_unique" in names


def test_macro_indexes_created(neo4j_test_driver):
    """Four indexes named macro_* / asset_* must exist after migration.

    In Neo4j 5+, every UNIQUE constraint auto-creates a backing B-tree index
    on the same property and the index inherits the constraint name — so the
    two constraint-backed indexes are named after the constraints
    (`macro_indicator_id_unique`, `asset_symbol_unique`) rather than via a
    separate `*_lookup` declaration.
    """
    with neo4j_test_driver.session() as session:
        result = session.run(
            "SHOW INDEXES WHERE name STARTS WITH 'macro_' OR name STARTS WITH 'asset_'"
        )
        names = {record["name"] for record in result}
        # Two node indexes auto-created by the UNIQUE constraints
        assert "macro_indicator_id_unique" in names
        assert "asset_symbol_unique" in names
        # Two explicit relationship-property indexes
        assert "macro_affects_strength_idx" in names
        assert "macro_drives_strength_idx" in names
        # Exactly 4 macro_*/asset_* indexes total — no stragglers
        assert len(names) == 4, f"Expected 4 macro_/asset_ indexes, got: {names}"


def test_relationship_property_index_neo4j_5_syntax(neo4j_test_driver):
    """The relationship-property index is created via the Neo4j 5+ form,
    verifiable by inspecting the index entityType + properties.

    Neo4j 5+ requires `YIELD` before `WHERE` on SHOW INDEXES (the inverse of
    SHOW CONSTRAINTS); using `WHERE … YIELD` raises CypherSyntaxError.
    """
    with neo4j_test_driver.session() as session:
        result = session.run(
            "SHOW INDEXES YIELD name, entityType, properties "
            "WHERE name = 'macro_affects_strength_idx'"
        )
        row = result.single()
        assert row is not None, "macro_affects_strength_idx not found"
        assert row["entityType"] == "RELATIONSHIP"
        assert row["properties"] == ["strength"]
