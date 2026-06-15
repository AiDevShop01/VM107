"""Wave 0 constraint enforcement — duplicate id/symbol inserts must fail.

Plan 87-02 VALIDATION row 87-00-02: the macro_indicator_id_unique and
asset_symbol_unique constraints actually reject duplicate inserts (not just
SHOW CONSTRAINTS lip-service). Cypher does NOT enforce property presence —
that's the Plan 87-03 loader's job; presence absence is verified separately.

Per project lock: no env defaults, no hardcoded URLs.
"""
import pytest
from neo4j.exceptions import ConstraintError

pytestmark = pytest.mark.phase_87


def test_duplicate_macro_indicator_id_rejected(neo4j_test_driver):
    with neo4j_test_driver.session() as session:
        session.run(
            "MERGE (i:MacroIndicator {id: 'CPIAUCSL'}) SET i.name = 'CPI'"
        )
        with pytest.raises(ConstraintError):
            # CREATE forces a brand-new node; uniqueness constraint must reject.
            session.run("CREATE (i:MacroIndicator {id: 'CPIAUCSL', name: 'Dup'})")

        # Cleanup to keep fixture state predictable.
        session.run("MATCH (i:MacroIndicator {id: 'CPIAUCSL'}) DETACH DELETE i")


def test_duplicate_asset_symbol_rejected(neo4j_test_driver):
    with neo4j_test_driver.session() as session:
        session.run("MERGE (a:Asset {symbol: 'XAUUSD'}) SET a.class = 'commodity'")
        with pytest.raises(ConstraintError):
            session.run("CREATE (a:Asset {symbol: 'XAUUSD', class: 'commodity'})")

        session.run("MATCH (a:Asset {symbol: 'XAUUSD'}) DETACH DELETE a")


def test_macro_indicator_without_id_inserts(neo4j_test_driver):
    """Uniqueness != presence. Loader enforces presence; schema does not."""
    with neo4j_test_driver.session() as session:
        session.run("CREATE (i:MacroIndicator {name: 'No id node'})")
        count = session.run(
            "MATCH (i:MacroIndicator) WHERE i.id IS NULL RETURN count(i) AS c"
        ).single()["c"]
        assert count == 1
        session.run("MATCH (i:MacroIndicator) WHERE i.id IS NULL DETACH DELETE i")
