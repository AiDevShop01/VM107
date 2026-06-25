"""Phase 92 Plan 4 — Wave 0 RED test for indicator → research → asset traversal.

Loads a 50-doc synthetic fixture into a live Neo4j test instance, then
exercises the ``GraphSearchTool`` template ``find_research_for_indicator`` 10
times and measures p95 latency.

Skip behavior (MINOR-6):
    The test is auto-skipped when no Neo4j bolt endpoint responds on
    localhost:7687. Operator can spin one up with:
        ``docker compose -f docker-compose.test.yml up neo4j-test``

Success criteria:
    - The tool returns a non-empty list of dicts with the documented columns
    - p95 latency < 200 ms over 10 hot-cache calls

REQ-92-5: graph traversal indicator→research→asset ≤ 200 ms p95.
"""
from __future__ import annotations

import importlib
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest


pytestmark = [
    pytest.mark.phase92,
    pytest.mark.skipif(
        # Lazy probe via conftest helper (defined in tests/research/conftest.py).
        # If the helper is missing (older conftest), we skip defensively.
        "True" if not (lambda: __import__("socket"))() else "False",
        reason="placeholder — replaced below",
    ),
]


# Replace the placeholder skipif with a real probe at import time.
def _neo4j_available_or_skip():
    try:
        # conftest defines _try_connect_neo4j / neo4j_available
        from tests.research.conftest import _try_connect_neo4j  # type: ignore
    except Exception:
        try:
            import socket

            with socket.create_connection(("localhost", 7687), timeout=2.0):
                return True
        except Exception:
            return False
    return _try_connect_neo4j(timeout=2.0)


pytestmark = [
    pytest.mark.phase92,
    pytest.mark.skipif(
        not _neo4j_available_or_skip(),
        reason=(
            "Neo4j test instance not running — start with "
            "`docker compose -f docker-compose.test.yml up neo4j-test`"
        ),
    ),
]


_VM101_BACKEND = Path("/Volumes/ HardDrive/FinGPT/VM101/backend")
_VM107_ROOT = Path("/Volumes/ HardDrive/FinGPT/VM107")


@pytest.fixture(scope="module")
def _vm_paths_on_sys_path():
    for p in (_VM101_BACKEND, _VM107_ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    yield


@pytest.fixture(scope="module")
def neo4j_driver(_vm_paths_on_sys_path):
    """Connect to the local Neo4j bolt endpoint and load 50 synthetic docs."""
    from neo4j import GraphDatabase  # type: ignore

    uri = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_TEST_USER", "neo4j")
    password = os.environ.get("NEO4J_TEST_PASSWORD", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    # Seed: 50 ResearchDocuments, each DISCUSSES_INDICATOR CPIAUCSL and
    # AFFECTS_ASSET one of {GOLD, UST10Y, DXY}.
    test_run_id = f"phase92plan4_{uuid.uuid4().hex[:8]}"
    with driver.session() as session:
        # Create indicator + 3 assets
        session.run(
            "MERGE (i:EconomicIndicator {id:'CPIAUCSL'}) SET i.test_run_id=$rid",
            rid=test_run_id,
        )
        session.run(
            "UNWIND ['GOLD','UST10Y','DXY'] AS aid "
            "MERGE (a:Asset {id: aid}) SET a.test_run_id=$rid",
            rid=test_run_id,
        )
        # Create 50 docs + edges
        for n in range(50):
            doc_id = f"rd_test_{test_run_id}_{n:03d}"
            asset_id = ["GOLD", "UST10Y", "DXY"][n % 3]
            session.run(
                """
                MERGE (rd:ResearchDocument {document_id:$doc_id})
                SET rd.title=$title, rd.tier=1,
                    rd.published_at = datetime() - duration({days: $n}),
                    rd.test_run_id=$rid
                WITH rd
                MATCH (i:EconomicIndicator {id:'CPIAUCSL'})
                MATCH (a:Asset {id:$asset_id})
                MERGE (rd)-[:DISCUSSES_INDICATOR {confidence:0.95, linker_stage:'synonym'}]->(i)
                MERGE (rd)-[:AFFECTS_ASSET {confidence:0.85, direction:'positive',
                                            via_indicator:'CPIAUCSL'}]->(a)
                """,
                doc_id=doc_id,
                title=f"Synthetic doc {n}",
                n=n,
                rid=test_run_id,
                asset_id=asset_id,
            )

    yield driver

    # Cleanup — delete only this test run's data
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.test_run_id=$rid DETACH DELETE n",
            rid=test_run_id,
        )
    driver.close()


def _load_tool(_vm_paths_on_sys_path):
    return importlib.import_module("tools.graph.graph_search_tool").GraphSearchTool


def test_template_registered(_vm_paths_on_sys_path):
    """The Cypher template catalog must expose find_research_for_indicator."""
    GraphSearchTool = _load_tool(_vm_paths_on_sys_path)
    # Allow either CYPHER_TEMPLATES dict key or _TEMPLATES path catalog —
    # implementation-defined. Just check at least one of the surfaces resolves.
    templates_attr = getattr(GraphSearchTool, "CYPHER_TEMPLATES", {})
    template_paths_attr = getattr(GraphSearchTool, "TEMPLATE_FILES", {})
    assert (
        "find_research_for_indicator" in templates_attr
        or "find_research_for_indicator" in template_paths_attr
    ), "Plan 4 must register find_research_for_indicator in GraphSearchTool"


def test_indicator_to_research_to_asset_traversal_returns_results(neo4j_driver):
    GraphSearchTool = _load_tool(True)
    GraphSearchTool.neo4j_driver = neo4j_driver

    # Plan-4 surface: ``run_template(name, params)`` returns list[dict].
    if hasattr(GraphSearchTool, "run_template"):
        instance = GraphSearchTool()
        rows = instance.run_template(
            "find_research_for_indicator", {"indicator_id": "CPIAUCSL", "limit": 20}
        )
    else:
        # Fallback: call CYPHER_TEMPLATES dict directly.
        with neo4j_driver.session() as s:
            result = s.run(
                GraphSearchTool.CYPHER_TEMPLATES["find_research_for_indicator"],
                indicator_id="CPIAUCSL",
                limit=20,
            )
            rows = [dict(r) for r in result]

    assert rows, "Plan 4 traversal returned no rows on 50-doc fixture"
    assert len(rows) <= 20, "limit=20 not honoured"
    sample = rows[0]
    for required_key in ("doc_id", "tier", "assets"):
        assert required_key in sample, f"missing key {required_key!r} in row {sample!r}"


def test_p95_latency_under_200ms(neo4j_driver):
    """REQ-92-5: 10 hot-cache calls; p95 < 200 ms."""
    GraphSearchTool = _load_tool(True)
    GraphSearchTool.neo4j_driver = neo4j_driver

    def _one_call() -> float:
        t0 = time.perf_counter()
        if hasattr(GraphSearchTool, "run_template"):
            GraphSearchTool().run_template(
                "find_research_for_indicator", {"indicator_id": "CPIAUCSL", "limit": 20}
            )
        else:
            with neo4j_driver.session() as s:
                list(
                    s.run(
                        GraphSearchTool.CYPHER_TEMPLATES["find_research_for_indicator"],
                        indicator_id="CPIAUCSL",
                        limit=20,
                    )
                )
        return (time.perf_counter() - t0) * 1000.0

    # 1 warm-up + 10 measured
    _one_call()
    samples_ms = [_one_call() for _ in range(10)]

    sorted_ms = sorted(samples_ms)
    # p95 with n=10: index 9 (the max). Use statistics.quantiles for n>=10.
    p95 = sorted_ms[int(0.95 * (len(sorted_ms) - 1))]
    assert p95 < 200.0, (
        f"p95 traversal latency {p95:.1f} ms exceeds 200 ms REQ-92-5 ceiling. "
        f"samples_ms={[round(x, 1) for x in samples_ms]}"
    )
