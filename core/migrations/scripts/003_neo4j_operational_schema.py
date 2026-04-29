"""
Neo4j operational subgraph schema creation.

Creates constraints and indexes for 14 operational node labels and
sets up indexes for common query patterns. This migration requires
both MongoDB (for tracking) and Neo4j (for schema creation).
"""


def upgrade(context: dict) -> None:
    """
    Create Neo4j operational schema: constraints and indexes.

    Args:
        context: Migration context with 'neo4j' driver and 'mongo' databases
    """
    neo4j_driver = context.get("neo4j")
    if not neo4j_driver:
        print("SKIP: Neo4j driver not available")
        return

    # Operational node labels (14 types)
    OPERATIONAL_LABELS = [
        "Strategy",
        "Feature",
        "FeatureSet",
        "Signal",
        "BacktestRun",
        "PerformanceMetric",
        "Agent",
        "Tool",
        "Task",
        "Dataset",
        "ValidationRun",
        "Regime",
        "Session",
        "InstrumentProfile",
    ]

    with neo4j_driver.session() as session:
        # Create unique constraints for each operational label
        for label in OPERATIONAL_LABELS:
            constraint_name = f"constraint_{label.lower()}_id_unique"
            cypher = f"""
            CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
            FOR (n:{label})
            REQUIRE n.id IS UNIQUE
            """
            session.run(cypher)
            print(f"✓ Created constraint for :{label}")

        # Create indexes for common query patterns
        indexes = [
            ("Strategy", "name"),
            ("Feature", "name"),
            ("Agent", "name"),
            ("InstrumentProfile", "name"),
        ]

        for label, property_name in indexes:
            index_name = f"index_{label.lower()}_{property_name}"
            cypher = f"""
            CREATE INDEX {index_name} IF NOT EXISTS
            FOR (n:{label})
            ON (n.{property_name})
            """
            session.run(cypher)
            print(f"✓ Created index for :{label}.{property_name}")

        # Create relationship index for timeframe-based correlation queries
        # Note: This creates a relationship index in Neo4j 5.x
        rel_index_cypher = """
        CREATE INDEX index_correlated_with_timeframe IF NOT EXISTS
        FOR ()-[r:CORRELATED_WITH]-()
        ON (r.timeframe)
        """
        session.run(rel_index_cypher)
        print("✓ Created relationship index for CORRELATED_WITH.timeframe")

        print(f"\n✓ Migration complete: {len(OPERATIONAL_LABELS)} constraints, {len(indexes)} node indexes, 1 relationship index created")


def downgrade(context: dict) -> None:
    """
    Drop Neo4j operational schema (requires confirmation).

    WARNING: This will drop all constraints and indexes, but NOT the data.
    Nodes and relationships will remain, but without constraints.

    Args:
        context: Migration context with 'neo4j' driver
    """
    neo4j_driver = context.get("neo4j")
    if not neo4j_driver:
        print("SKIP: Neo4j driver not available")
        return

    # For safety, we just document what would be dropped
    # Actual implementation would require explicit confirmation flag
    print("DOWNGRADE: Would drop operational schema constraints and indexes")
    print("To implement: Add confirmation flag and DROP CONSTRAINT/INDEX commands")
