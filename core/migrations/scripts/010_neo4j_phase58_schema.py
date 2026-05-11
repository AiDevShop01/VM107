"""
Neo4j Phase 58 schema migration: :Execution + :BehavioralPattern unique constraints.

Adds 2 new unique constraints + 2 supporting indexes to enable the canonical
post-trade intelligence projector (ExecutionNeo4jProjector — body lands 58-03):

  - CONSTRAINT execution_id_unique           ON (e:Execution)        REQUIRE e.id IS UNIQUE
  - CONSTRAINT behavioral_pattern_id_unique  ON (b:BehavioralPattern) REQUIRE b.id IS UNIQUE
  - INDEX     execution_strategy_idx        ON (e:Execution)        FOR (e.strategy_id)
  - INDEX     execution_instrument_idx      ON (e:Execution)        FOR (e.instrument_id)

CONTEXT cross-reference:
  - 58-CONTEXT.md §6 (Neo4j scope — strict relationship-only graph)
  - 58-CONTEXT.md §7 (V1 edge taxonomy — :Execution-[]->:Strategy/:Instrument/etc.)
  - 58-CONTEXT.md §8 (BehavioralPattern controlled vocabulary)

Why now: the Wave 5 fan-out sensor + ExecutionNeo4jProjector will MERGE
:Execution {id: <uuid>} on every snapshot — without the unique constraint,
duplicate :Execution nodes would silently accumulate (RESEARCH Pitfall 3).
Same for :BehavioralPattern when Phase 57 behavioral analysis fires
:FAILED_DUE_TO edges.

Idempotent: every CREATE statement uses IF NOT EXISTS. Re-running this
migration after it has already applied is a no-op.

Phase 4 / migration 003 constraints (:Strategy / :Instrument / :Regime)
are NOT touched — they remain in place after this migration runs.

Phase 58-01 contract — accompanies migration 0024_analytics_projection_ledger
on the Postgres side. No data touched, schema only.
"""


CONSTRAINTS = [
    (
        "execution_id_unique",
        "CREATE CONSTRAINT execution_id_unique IF NOT EXISTS "
        "FOR (e:Execution) REQUIRE e.id IS UNIQUE",
    ),
    (
        "behavioral_pattern_id_unique",
        "CREATE CONSTRAINT behavioral_pattern_id_unique IF NOT EXISTS "
        "FOR (b:BehavioralPattern) REQUIRE b.id IS UNIQUE",
    ),
]

INDEXES = [
    (
        "execution_strategy_idx",
        "CREATE INDEX execution_strategy_idx IF NOT EXISTS "
        "FOR (e:Execution) ON (e.strategy_id)",
    ),
    (
        "execution_instrument_idx",
        "CREATE INDEX execution_instrument_idx IF NOT EXISTS "
        "FOR (e:Execution) ON (e.instrument_id)",
    ),
]


def upgrade(context: dict) -> None:
    """Create :Execution + :BehavioralPattern constraints + Execution indexes.

    Args:
        context: Migration context with 'neo4j' driver (and 'mongo' for tracking).
    """
    neo4j_driver = context.get("neo4j")
    if not neo4j_driver:
        print("SKIP: Neo4j driver not available")
        return

    with neo4j_driver.session() as session:
        for name, cypher in CONSTRAINTS:
            session.run(cypher)
            print(f"✓ Created constraint :{name}")

        for name, cypher in INDEXES:
            session.run(cypher)
            print(f"✓ Created index :{name}")

        print(
            f"\n✓ Migration complete: "
            f"{len(CONSTRAINTS)} constraints + {len(INDEXES)} indexes "
            f"(Phase 58-01)"
        )


def downgrade(context: dict) -> None:
    """Drop the Phase 58 constraints + indexes (data preserved).

    WARNING: dropping constraints does NOT delete :Execution or
    :BehavioralPattern nodes — only the uniqueness/index metadata.
    """
    neo4j_driver = context.get("neo4j")
    if not neo4j_driver:
        print("SKIP: Neo4j driver not available")
        return

    with neo4j_driver.session() as session:
        for name, _ in INDEXES:
            session.run(f"DROP INDEX {name} IF EXISTS")
            print(f"✓ Dropped index :{name}")

        for name, _ in CONSTRAINTS:
            session.run(f"DROP CONSTRAINT {name} IF EXISTS")
            print(f"✓ Dropped constraint :{name}")

        print("✓ Phase 58 schema downgraded (data preserved)")
