"""Wave 1 idempotency — second loader run produces zero new edges.

Runs the FULL 12-indicator seed against a session-scoped testcontainers Neo4j
and asserts REQ-87-1 (>=60 AFFECTS + >=30 DRIVES) on the first run and
REQ-87-1b (idempotency: zero new edges on second run).
"""
from __future__ import annotations

import pathlib

import pytest

from services.macro_graph.loader import MacroGraphLoader

pytestmark = pytest.mark.phase_87

FULL_SEED = (
    pathlib.Path(__file__).parent.parent.parent.parent
    / "vm105" / "seeds" / "macro_graph_seed.yaml"
)


class _NullAugmenter:
    """Test double — never calls VM102; always returns the YAML fallback degraded."""

    def augment_affects(self, **kwargs):
        from dataclasses import replace
        return replace(kwargs["yaml_fallback"], degraded=True)

    def augment_drives(self, **kwargs):
        from dataclasses import replace
        return replace(kwargs["yaml_fallback"], degraded=True)


@pytest.fixture(scope="module")
def fresh_neo4j_driver():
    """Module-scoped driver — independent of the session driver so the
    idempotency test starts from a clean graph."""
    from testcontainers.neo4j import Neo4jContainer

    migration_path = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "vm105" / "migrations" / "0087_macro_graph_schema.cypher"
    )
    if not migration_path.exists():
        pytest.xfail(
            "Plan 87-02 not landed yet — 0087_macro_graph_schema.cypher missing"
        )

    with Neo4jContainer("neo4j:5.15") as neo4j:
        driver = neo4j.get_driver()
        with driver.session() as session:
            cypher_text = migration_path.read_text()
            for stmt in [s.strip() for s in cypher_text.split(";\n") if s.strip()]:
                session.run(stmt)
        yield driver
        driver.close()


def test_full_seed_first_run_meets_req_87_1(fresh_neo4j_driver):
    """First run: 12 indicators created, >=60 AFFECTS, >=30 DRIVES."""
    loader = MacroGraphLoader(
        seed_yaml_path=FULL_SEED,
        augmenter=_NullAugmenter(),
        neo4j_driver=fresh_neo4j_driver,
    )
    report = loader.load(dry_run=False, check_schema=True)
    assert report.indicators_created == 12, (
        f"expected 12 indicators created, got {report.indicators_created}"
    )
    assert report.affects_created >= 60, (
        f"REQ-87-1 violated: expected >=60 AFFECTS, got {report.affects_created}"
    )
    assert report.drives_created >= 30, (
        f"REQ-87-1 violated: expected >=30 DRIVES, got {report.drives_created}"
    )


def test_full_seed_second_run_is_idempotent(fresh_neo4j_driver):
    """Second run: zero new edges + zero new indicators (REQ-87-1b)."""
    # Note: this test runs AFTER the first-run test (module-scoped fixture
    # preserves the graph). The first run populated the graph; we run again.
    loader = MacroGraphLoader(
        seed_yaml_path=FULL_SEED,
        augmenter=_NullAugmenter(),
        neo4j_driver=fresh_neo4j_driver,
    )

    with fresh_neo4j_driver.session() as session:
        affects_before = session.run(
            "MATCH ()-[r:AFFECTS]->() RETURN count(r) AS c"
        ).single()["c"]
        drives_before = session.run(
            "MATCH ()-[r:DRIVES]->() RETURN count(r) AS c"
        ).single()["c"]
        indicators_before = session.run(
            "MATCH (i:MacroIndicator) RETURN count(i) AS c"
        ).single()["c"]

    report = loader.load(dry_run=False, check_schema=True)
    assert report.indicators_created == 0, (
        f"REQ-87-1b violated: second run created {report.indicators_created} "
        f"new indicators"
    )
    assert report.affects_created == 0, (
        f"REQ-87-1b violated: second run created {report.affects_created} new AFFECTS"
    )
    assert report.drives_created == 0, (
        f"REQ-87-1b violated: second run created {report.drives_created} new DRIVES"
    )

    with fresh_neo4j_driver.session() as session:
        affects_after = session.run(
            "MATCH ()-[r:AFFECTS]->() RETURN count(r) AS c"
        ).single()["c"]
        drives_after = session.run(
            "MATCH ()-[r:DRIVES]->() RETURN count(r) AS c"
        ).single()["c"]
        indicators_after = session.run(
            "MATCH (i:MacroIndicator) RETURN count(i) AS c"
        ).single()["c"]

    assert affects_after == affects_before
    assert drives_after == drives_before
    assert indicators_after == indicators_before
