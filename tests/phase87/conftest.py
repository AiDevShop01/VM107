"""Phase 87 shared fixtures — consumed by Waves 2-7 integration tests.

Per project lock:
  - NO `os.getenv("X", "default")` patterns — env-driven config fail-fast.
  - All cross-VM URLs (Neo4j, Qdrant, BeliefStore Postgres) come from
    docker-compose env vars in production; tests use testcontainers.

Fixtures exposed (8):
  - neo4j_test_driver         — testcontainers Neo4j 5.15 + Wave 0 schema migration
  - qdrant_test_client        — testcontainers Qdrant 1.7 + empty macro_episode collection
  - release_event_factory     — callable producing Phase 83 econ_release payloads
  - anchor_indicator_history  — 24 months of CPI/UNRATE/GDP releases (from fixture file)
  - belief_store_stub         — MagicMock with flat 0.5 prior for Wave 3 pre-Wave-5 period
  - episodic_memory_stub      — MagicMock returning empty memories for Wave 2 pre-Wave-4
  - hand_curated_seed_minimal — 3-indicator seed YAML loaded as dict
  - anchor_combinations       — 7 explicit dir-tuple → expected_regime mappings
"""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

PHASE_87_SEED = 87  # deterministic — do not change without re-vendoring fixtures
FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.phase_87


# ─── Containerised Neo4j (Wave 2 walker tool tests; Wave 1 loader tests) ─────
@pytest.fixture(scope="session")
def neo4j_test_driver():
    """Testcontainers Neo4j 5.15 with Wave 0 macro schema migration applied.

    Plan 87-02 creates the migration file at
    vm105/migrations/0087_macro_graph_schema.cypher. If that file does not
    exist yet, this fixture xfails — Plan 87-01 can still ship.
    """
    migration_path = (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "vm105"
        / "migrations"
        / "0087_macro_graph_schema.cypher"
    )
    if not migration_path.exists():
        pytest.xfail(
            "Plan 87-02 not landed yet — 0087_macro_graph_schema.cypher missing"
        )

    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5.15") as neo4j:
        driver = neo4j.get_driver()
        with driver.session() as session:
            cypher_text = migration_path.read_text()
            # Split on `;` newline — each Cypher statement runs separately
            for stmt in [s.strip() for s in cypher_text.split(";\n") if s.strip()]:
                session.run(stmt)
        yield driver
        driver.close()


# ─── Containerised Qdrant (Wave 4 B6 EpisodicMemoryService tests) ────────────
@pytest.fixture(scope="session")
def qdrant_test_client():
    """Testcontainers Qdrant 1.7 with empty macro_episode collection.

    testcontainers does not ship a first-class Qdrant adapter — use the
    generic DockerContainer wrapper. Proven on Mac Docker dev.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm
    from testcontainers.core.container import DockerContainer

    # v1.13.0 supports the /collections/{c}/points/query endpoint that
    # qdrant_client>=1.10 emits via .query_points() (the .search() method is
    # deprecated upstream). Plan 87-07 Wave 4a required the bump.
    with DockerContainer("qdrant/qdrant:v1.13.0").with_exposed_ports(6333) as ctr:
        host = ctr.get_container_host_ip()
        port = int(ctr.get_exposed_port(6333))
        client = QdrantClient(host=host, port=port)
        client.create_collection(
            collection_name="macro_episode",
            vectors_config=qm.VectorParams(size=768, distance=qm.Distance.COSINE),
        )
        client.create_payload_index(
            collection_name="macro_episode",
            field_name="indicator_id",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name="macro_episode",
            field_name="regime_at_episode",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        yield client


# ─── Phase 83 econ_release event factory ─────────────────────────────────────
@pytest.fixture
def release_event_factory():
    """Callable producing Phase 83 econ_release Redis topic payloads.

    Schema (matches Phase 83 econ_release topic exactly):
      indicator_id, release_id (uuid), release_date (ISO),
      actual, forecast, previous, surprise, surprise_pct, event_status
    """

    def _make(
        indicator_id: str = "CPIAUCSL",
        actual: float = 3.4,
        forecast: float = 3.3,
        previous: float = 3.2,
        surprise: float | None = None,
        event_status: str = "released",
        **overrides: Any,
    ) -> dict:
        payload = {
            "indicator_id": indicator_id,
            "release_id": str(uuid.uuid4()),
            "release_date": datetime.now(tz=timezone.utc).isoformat(),
            "actual": actual,
            "forecast": forecast,
            "previous": previous,
            "surprise": surprise if surprise is not None else (actual - forecast),
            "surprise_pct": ((actual - forecast) / forecast) * 100 if forecast else 0,
            "event_status": event_status,
        }
        payload.update(overrides)
        return payload

    return _make


# ─── 24-month anchor indicator release history (Wave 5 BeliefStore calibration) ─
@pytest.fixture
def anchor_indicator_history():
    path = FIXTURES_DIR / "regime_history_2yr.json"
    if not path.exists():
        pytest.skip("Task 3 fixture not landed yet")
    return json.loads(path.read_text())


# ─── BeliefStore stub (Wave 3 pre-Wave-5 period) ─────────────────────────────
@pytest.fixture
def belief_store_stub():
    stub = MagicMock()
    stub.query.return_value = {
        "probability": 0.5,
        "confidence": 0.5,
        "evidence_count": 0,
    }
    # propose() raises AttributeError so Wave 3 cannot accidentally persist beliefs
    stub.propose.side_effect = AttributeError(
        "BeliefStore.propose not wired in Wave 3 stub — Wave 5 swaps for real client"
    )
    return stub


# ─── EpisodicMemoryService stub (Wave 2 pre-Wave-4 period) ───────────────────
@pytest.fixture
def episodic_memory_stub():
    stub = MagicMock()
    stub.query.return_value = {
        "memories_retrieved": [],
        "confidence": 0.0,
        "cache_hit": False,
    }
    return stub


# ─── Hand-curated minimal seed (Wave 1 idempotency + Wave 2 walker tests) ───
@pytest.fixture
def hand_curated_seed_minimal():
    import yaml

    path = FIXTURES_DIR / "macro_graph_seed_test.yaml"
    if not path.exists():
        pytest.skip("Task 3 fixture not landed yet")
    return yaml.safe_load(path.read_text())


# ─── Anchor combinations for regime classifier rule tests ───────────────────
@pytest.fixture
def anchor_combinations():
    path = FIXTURES_DIR / "anchor_indicator_releases.json"
    if not path.exists():
        pytest.skip("Task 3 fixture not landed yet")
    return json.loads(path.read_text())["anchor_combinations"]
