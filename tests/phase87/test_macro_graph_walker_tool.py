"""Phase 87 Wave 2 — Macro Graph Walker tool unit tests.

Walker invokes the VM100 internal endpoint at
``${VM100_INTERNAL_BASE_URL}/api/macro/internal/graph-walk/{indicator_id}``.

These tests stub the endpoint with ``httpx.MockTransport`` so they can
exercise the walker contract without standing up the full Django dev
server. A separate Plan-87-14 deploy-gate test against the real VM100
endpoint covers the integration surface.

Per project lock:
  - NO ``os.getenv("X", "default")`` patterns — the walker fails fast on
    missing ``VM100_INTERNAL_BASE_URL``.
  - NO hardcoded URLs — base url comes from env or explicit constructor arg.
"""
from __future__ import annotations

import os

import httpx
import pytest

from tools.neo4j_macro_graph_walker import Hop, Neo4jMacroGraphWalker

pytestmark = pytest.mark.phase_87


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_minimal_graph(driver):
    """Apply the Wave-0 minimal seed (3 indicators) to the testcontainers driver."""
    from services.macro_graph.loader import MacroGraphLoader
    import pathlib

    seed_path = (
        pathlib.Path(__file__).parent / "fixtures" / "macro_graph_seed_test.yaml"
    )

    class _NullAugmenter:
        def augment_affects(self, **kwargs):
            from dataclasses import replace
            return replace(kwargs["yaml_fallback"], degraded=True)

        def augment_drives(self, **kwargs):
            from dataclasses import replace
            return replace(kwargs["yaml_fallback"], degraded=True)

    MacroGraphLoader(
        seed_yaml_path=seed_path,
        augmenter=_NullAugmenter(),
        neo4j_driver=driver,
    ).load(dry_run=False, check_schema=True)


def _walker_with_neo4j_handler(driver) -> Neo4jMacroGraphWalker:
    """Build a walker whose httpx client routes /graph-walk through the driver.

    Mirrors the eventual VM100 endpoint behaviour without requiring the Django
    app: takes ``indicator_id`` from the URL path, runs the same Cypher walk
    that the production endpoint runs, returns the same shaped JSON payload.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        indicator_id = request.url.path.rsplit("/", 1)[-1]
        with driver.session() as session:
            rows = session.run(
                "MATCH (i:MacroIndicator {id: $id})-[r:AFFECTS]->(t:MacroIndicator) "
                "RETURN i.id AS source, t.id AS target, 'AFFECTS' AS rel, "
                "       r.strength AS strength, r.confidence AS confidence, "
                "       r.sample_size AS sample_size, "
                "       r.evidence_period AS period, "
                "       r.hop_order AS hop_order "
                "UNION "
                "MATCH (i:MacroIndicator {id: $id})-[d:DRIVES]->(a:Asset) "
                "RETURN i.id AS source, a.symbol AS target, 'DRIVES' AS rel, "
                "       d.strength AS strength, d.confidence AS confidence, "
                "       d.sample_size AS sample_size, "
                "       d.evidence_period AS period, "
                "       NULL AS hop_order",
                id=indicator_id,
            ).data()
        hops = [
            {
                "source": r["source"],
                "target": r["target"],
                "relationship_type": r["rel"],
                "strength": float(r["strength"]),
                "confidence": float(r["confidence"]),
                "sample_size": int(r["sample_size"]),
                "evidence_period": str(r["period"]),
                "hop_order": r["hop_order"],
            }
            for r in rows
        ]
        return httpx.Response(
            200, json={"indicator_id": indicator_id, "hops": hops}
        )

    walker = Neo4jMacroGraphWalker(vm100_internal_base_url="http://test")
    walker._client = httpx.Client(transport=httpx.MockTransport(_handler))
    return walker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_walker_returns_hops_for_seeded_indicator(neo4j_test_driver):
    """Walker against the Wave-0 minimal seed returns ≥3 hops for CPIAUCSL.

    Seed has CPI → UNRATE → GDP (AFFECTS chain) plus CPI → XAUUSD + CPI → SPX
    (DRIVES terminals) = 4 hops minimum out of CPIAUCSL.
    """
    _seed_minimal_graph(neo4j_test_driver)
    walker = _walker_with_neo4j_handler(neo4j_test_driver)
    hops = walker.walk("CPIAUCSL")

    assert len(hops) >= 3, f"expected >=3 hops for CPIAUCSL, got {len(hops)}"
    for hop in hops:
        assert isinstance(hop, Hop)
        assert hop.relationship_type in {"AFFECTS", "DRIVES"}
        assert 0.0 <= hop.confidence <= 1.0
        assert hop.sample_size > 0
        assert hop.evidence_period.count("/") == 1  # ISO date range "Y/Y"
        assert hop.source == "CPIAUCSL"


def test_walker_fails_fast_on_missing_env(monkeypatch):
    """Walker must raise RuntimeError when no base URL is supplied via env.

    Project lock: NO ``os.getenv("X", "default")`` fallback. Fail-fast at
    construction beats silent misconfiguration.
    """
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="VM100_INTERNAL_BASE_URL"):
        Neo4jMacroGraphWalker(vm100_internal_base_url=None)


def test_walker_picks_up_env_var(monkeypatch):
    """If env var IS set, walker constructs without explicit arg."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    walker = Neo4jMacroGraphWalker()
    assert walker._base == "http://vm100:8000"


def test_walker_strips_trailing_slash_from_base_url(monkeypatch):
    """Defensive: trailing slash on base URL should not double up the path."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000/")
    walker = Neo4jMacroGraphWalker()
    assert walker._base == "http://vm100:8000"
