"""Phase 92 Plan 05 — Wave 0 RED test for DiscoveryAgent.

Asserts:
- DiscoveryAgent.analyse() on a sample of 3+ docs supporting the same
  pattern emits a research_discovery_candidate event whose payload
  conforms to the schema mirroring alert_candidate_created.
- MongoDB write to `research_intelligence_discoveries` asserted.

RED until Task 2 ships VM107/agents/research/discovery_agent.py.
"""
from __future__ import annotations

from typing import Any

import pytest


pytestmark = pytest.mark.phase92


@pytest.fixture
def stub_summaries() -> list[dict[str, Any]]:
    """3 docs across 2 sources supporting the same key_finding."""
    return [
        {
            "doc_id": "doc-fomc-01",
            "indicator_id": "CPIAUCSL",
            "source": "fed_press_all",
            "key_findings": ["inflation_above_target", "labour_market_softening"],
            "tier": 1,
            "created_at": "2026-06-20T00:00:00Z",
        },
        {
            "doc_id": "doc-ecb-02",
            "indicator_id": "CPIAUCSL",
            "source": "ecb_press",
            "key_findings": ["inflation_above_target", "policy_data_dependent"],
            "tier": 1,
            "created_at": "2026-06-21T00:00:00Z",
        },
        {
            "doc_id": "doc-nber-03",
            "indicator_id": "CPIAUCSL",
            "source": "nber_papers",
            "key_findings": ["inflation_above_target", "inflation_persistence"],
            "tier": 3,
            "created_at": "2026-06-22T00:00:00Z",
        },
    ]


@pytest.fixture
def mock_mongo(monkeypatch, stub_summaries):
    storage: dict[str, list[dict[str, Any]]] = {
        "research_intelligence_summaries": list(stub_summaries),
        "research_intelligence_citations": [],
        "research_intelligence_contrarian": [],
        "research_intelligence_discoveries": [],
    }

    class _FakeCollection:
        def __init__(self, name: str) -> None:
            self._name = name

        def insert_one(self, doc: dict[str, Any]) -> Any:
            storage[self._name].append(doc)

            class _R:
                inserted_id = f"id-{len(storage[self._name])}"

            return _R()

        def find(self, query: dict | None = None, *_a, **_k):
            rows = storage[self._name]
            if not query:
                return list(rows)
            # naive query: support {"indicator_id": ..., "created_at": {"$gte": ...}}
            ind = query.get("indicator_id")
            out = [r for r in rows if (ind is None or r.get("indicator_id") == ind)]
            return iter(out)

        def create_index(self, *_a, **_k):
            return "idx"

    class _FakeDB:
        def __getattr__(self, name: str) -> _FakeCollection:
            if name not in storage:
                storage[name] = []
            return _FakeCollection(name)

    def _fake_get_db():
        return _FakeDB()

    monkeypatch.setattr(
        "agents.research.storage.get_db",
        _fake_get_db,
        raising=False,
    )
    return storage


@pytest.fixture
def mock_emit(monkeypatch):
    emitted: list[dict[str, Any]] = []

    def _fake_emit(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append({"event_type": event_type, "payload": payload})

    monkeypatch.setattr(
        "agents.research.discovery_agent.emit_event",
        _fake_emit,
        raising=False,
    )
    return emitted


def test_discovery_agent_emits_candidate_and_writes_mongo(
    stub_summaries, mock_mongo, mock_emit
):
    """RED until Task 2."""
    from agents.research.discovery_agent import DiscoveryAgent  # noqa: E501

    agent = DiscoveryAgent()
    result = agent.analyse(indicator_id="CPIAUCSL", lookback_days=30)

    # >= 1 candidate detected
    candidates = (
        getattr(result, "candidates", None) or result.get("candidates", [])
    )
    assert len(candidates) >= 1

    # Phase 91 event emitted
    assert len(mock_emit) >= 1
    e = mock_emit[0]
    assert e["event_type"] == "research_discovery_candidate"
    p = e["payload"]
    assert "discovery_id" in p
    assert "pattern_summary" in p
    assert "supporting_docs" in p and len(p["supporting_docs"]) >= 3
    assert "indicators" in p and "CPIAUCSL" in p["indicators"]
    assert "severity" in p  # mirrors alert_candidate_created
    assert "category" in p and p["category"] == "research_discovery"

    # MongoDB persistence
    written = mock_mongo["research_intelligence_discoveries"]
    assert len(written) >= 1
    rec = written[0]
    assert "discovery_id" in rec
    assert "pattern_summary" in rec
    assert "supporting_docs" in rec and len(rec["supporting_docs"]) >= 3
    assert "indicators" in rec
    assert "created_at" in rec
