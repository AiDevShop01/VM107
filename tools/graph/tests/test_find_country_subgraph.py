"""Phase 96 Plan 11 Task 1 — find_country_subgraph template tests.

REQ-96-9 — GraphSearchTool exposes ``find_country_subgraph(iso_alpha2, depth)``
returning the union of all edges within ``depth`` hops from the country node,
shaped as ``{nodes: [...], edges: [...]}``.

Contract:
    - depth bounds enforced 1..3; out-of-bounds → ValueError
    - unknown ISO → empty payload ``{nodes: [], edges: []}`` (NOT error)
    - parameterized Cypher — passing a Cypher-injection payload as ``iso``
      must NOT execute extra Cypher; it must return the empty payload
    - result deduplicates nodes by id and edges by (from_id, to_id, type)
    - depth=2 returns a non-smaller node set than depth=1 (monotonic)

Skip behaviour mirrors tests/research/test_graph_search_indicator_to_asset.py
— the suite is skipped when no Neo4j bolt endpoint responds on localhost:7687.
"""
from __future__ import annotations

import socket
import sys
import uuid
from pathlib import Path

import pytest

_VM107_ROOT = Path("/Volumes/ HardDrive/FinGPT/VM107")
_root = str(_VM107_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)


def _neo4j_available() -> bool:
    try:
        with socket.create_connection(("localhost", 7687), timeout=2.0):
            return True
    except Exception:
        return False


_NEO4J_UP = _neo4j_available()
neo4j_required = pytest.mark.skipif(
    not _NEO4J_UP,
    reason=(
        "Neo4j test instance not running — start with "
        "`docker compose -f docker-compose.test.yml up neo4j-test`"
    ),
)


# ---------------------------------------------------------------------------
# Unit tests that do NOT need Neo4j (bounds + empty-driver behaviour).
# These run in every environment so the contract surface is always pinned.
# ---------------------------------------------------------------------------


def _bare_tool(driver=None):
    """Build a GraphSearchTool instance without invoking the heavy
    ContractTool / agent_zero base ``__init__`` (which requires 6
    positional args: agent, name, method, args, message, loop_data).
    The bounds-check + None-driver paths only need the class methods and
    the ``neo4j_driver`` attribute.
    """
    from tools.graph.graph_search_tool import GraphSearchTool

    tool = GraphSearchTool.__new__(GraphSearchTool)
    tool.neo4j_driver = driver
    return tool


def test_depth_out_of_bounds_raises_without_driver():
    """Bounds check fires before any Neo4j call — runs without a live driver."""
    tool = _bare_tool()
    with pytest.raises(ValueError):
        tool.find_country_subgraph("US", depth=4)
    with pytest.raises(ValueError):
        tool.find_country_subgraph("US", depth=0)
    with pytest.raises(ValueError):
        tool.find_country_subgraph("US", depth=-1)


def test_depth_must_be_integer_without_driver():
    """Non-int depth (float, str, bool) is also a bounds violation."""
    tool = _bare_tool()
    with pytest.raises(ValueError):
        tool.find_country_subgraph("US", depth=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        tool.find_country_subgraph("US", depth="1")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        tool.find_country_subgraph("US", depth=True)  # type: ignore[arg-type]


def test_no_driver_returns_empty_payload():
    """Graceful degradation — None driver yields empty payload (NOT raises)."""
    tool = _bare_tool(driver=None)
    result = tool.find_country_subgraph("US", depth=1)
    assert result == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Integration tests against a live Neo4j fixture.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def neo4j_driver():
    """Module-level neo4j driver against localhost:7687."""
    from neo4j import GraphDatabase

    uri = "bolt://localhost:7687"
    auth = ("neo4j", "fingpt-test")
    drv = GraphDatabase.driver(uri, auth=auth)
    yield drv
    drv.close()


@pytest.fixture
def us_subgraph(neo4j_driver):
    """Seed: US Country + USD Currency + Fed CentralBank + US Government
    + EXPORTS_TO edges to CA and MX. Uses a unique tag prefix to avoid
    cross-test bleed in a shared graph.
    """
    tag = f"p96p11_{uuid.uuid4().hex[:8]}"
    with neo4j_driver.session() as s:
        # Clean any pre-existing nodes carrying this tag (safety).
        s.run(
            "MATCH (n) WHERE n._phase96_plan11_tag = $tag DETACH DELETE n",
            tag=tag,
        )
        s.run(
            """
            MERGE (us:Country {iso_alpha2: 'US'})
              ON CREATE SET us.name = 'United States'
              SET us._phase96_plan11_tag = $tag
            MERGE (usd:Currency {code: 'USD'})
              SET usd._phase96_plan11_tag = $tag
            MERGE (fed:CentralBank {name: 'Federal Reserve'})
              SET fed._phase96_plan11_tag = $tag
            MERGE (govt:Government {name: 'United States Government'})
              SET govt._phase96_plan11_tag = $tag
            MERGE (us)-[:ISSUES_CURRENCY]->(usd)
            MERGE (us)-[:HAS_CENTRAL_BANK]->(fed)
            MERGE (us)-[:HAS_GOVERNMENT]->(govt)
            MERGE (ca:Country {iso_alpha2: 'CA'})
              ON CREATE SET ca.name = 'Canada'
              SET ca._phase96_plan11_tag = $tag
            MERGE (mx:Country {iso_alpha2: 'MX'})
              ON CREATE SET mx.name = 'Mexico'
              SET mx._phase96_plan11_tag = $tag
            MERGE (us)-[:EXPORTS_TO {share_pct: 17.8}]->(ca)
            MERGE (us)-[:EXPORTS_TO {share_pct: 15.7}]->(mx)
            """,
            tag=tag,
        )
    yield neo4j_driver
    with neo4j_driver.session() as s:
        s.run(
            "MATCH (n) WHERE n._phase96_plan11_tag = $tag DETACH DELETE n",
            tag=tag,
        )


@pytest.fixture
def graph_tool(us_subgraph):
    """GraphSearchTool wired to the live Neo4j driver.

    Uses ``__new__`` to bypass the heavy ContractTool ``__init__``
    (6 positional args). The bounds check + Cypher exec paths only need
    the instance methods and the ``neo4j_driver`` attribute.
    """
    from tools.graph.graph_search_tool import GraphSearchTool

    tool = GraphSearchTool.__new__(GraphSearchTool)
    tool.neo4j_driver = us_subgraph
    return tool


@neo4j_required
def test_depth_1_returns_immediate_neighbors(graph_tool):
    result = graph_tool.find_country_subgraph("US", depth=1)
    assert isinstance(result, dict)
    assert "nodes" in result and "edges" in result
    labels_seen = {
        (n["labels"][0] if n.get("labels") else None)
        for n in result["nodes"]
    }
    # US Country itself + at least one of Currency / CentralBank / Government / Country.
    assert "Country" in labels_seen
    # At least 1 edge — ISSUES_CURRENCY, HAS_CENTRAL_BANK, HAS_GOVERNMENT, or EXPORTS_TO.
    assert len(result["edges"]) >= 1


@neo4j_required
def test_depth_2_monotonic_with_depth_1(graph_tool):
    r1 = graph_tool.find_country_subgraph("US", depth=1)
    r2 = graph_tool.find_country_subgraph("US", depth=2)
    assert len(r2["nodes"]) >= len(r1["nodes"]), (
        f"depth=2 node count {len(r2['nodes'])} < depth=1 count {len(r1['nodes'])} — "
        "graph traversal should be monotonic in depth."
    )


@neo4j_required
def test_unknown_iso_returns_empty(graph_tool):
    # 'ZZ' is reserved/unused in ISO 3166-1; the seed does not create it.
    result = graph_tool.find_country_subgraph("ZZ", depth=1)
    assert result == {"nodes": [], "edges": []}


@neo4j_required
def test_nodes_deduplicated(graph_tool):
    result = graph_tool.find_country_subgraph("US", depth=2)
    node_ids = [n["id"] for n in result["nodes"]]
    assert len(node_ids) == len(set(node_ids)), (
        "Duplicate node ids in result — find_country_subgraph must dedupe."
    )


@neo4j_required
def test_iso_parameterized_not_string_formatted(graph_tool):
    """Cypher safety smoke check.

    Passing a Cypher-injection payload as the ISO must NOT execute the
    injected fragment. The query uses parameterized ``$iso`` binding, so
    a malformed value simply matches no Country and returns the empty
    payload.
    """
    payload = "US'} OR true RETURN n {.id} AS x //"
    result = graph_tool.find_country_subgraph(payload, depth=1)
    assert result == {"nodes": [], "edges": []}
