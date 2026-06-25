"""Phase 92 Plan 05 — Wave 0 RED test for ContrarianAgent.

Asserts:
- Contrarian claim text containing the canonical "Higher CPI did NOT
  correlate with gold appreciation" example surfaces a contrarian_claim
  with linked indicator + confidence.
- MongoDB write to `research_intelligence_contrarian` asserted.

RED until Task 2 ships VM107/agents/research/contrarian_agent.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


pytestmark = pytest.mark.phase92


@dataclass
class _StubResearchDoc:
    document_id: str
    indicators: list[str]
    tier: int
    title: str
    body: str


@pytest.fixture
def stub_contrarian_doc() -> _StubResearchDoc:
    return _StubResearchDoc(
        document_id="doc-nber-contrarian-01",
        indicators=["CPIAUCSL"],
        tier=3,
        title="Reassessing Gold-Inflation Comovement: 2022 as a Counterexample",
        body=(
            "Conventional wisdom holds that gold appreciates during inflationary "
            "episodes. However, during 2022 — the most acute inflationary "
            "episode of the past four decades — higher CPI prints did NOT "
            "correlate with gold appreciation; instead, gold underperformed "
            "broad equity benchmarks. We argue that the dollar regime and "
            "real-rate trajectory dominate."
        ),
    )


@pytest.fixture
def mock_llm(monkeypatch):
    canned = (
        '{"contrarian_claim": "Higher CPI did NOT correlate with gold '
        'appreciation in the 2022 episode.", '
        '"evidence_chunks": ["higher CPI prints did NOT correlate with gold appreciation"], '
        '"confidence": 0.82}'
    )

    def _fake_call(prompt: str) -> str:
        return canned

    monkeypatch.setattr("services.llm_client.call_llm", _fake_call, raising=False)
    return _fake_call


@pytest.fixture
def mock_mongo(monkeypatch):
    storage: dict[str, list[dict[str, Any]]] = {
        "research_intelligence_summaries": [],
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


def test_contrarian_agent_surfaces_claim_and_writes_mongo(
    stub_contrarian_doc, mock_llm, mock_mongo
):
    """RED until Task 2."""
    from agents.research.contrarian_agent import ContrarianAgent  # noqa: E501

    agent = ContrarianAgent()
    result = agent.process(stub_contrarian_doc)

    claim = getattr(result, "contrarian_claim", None) or result.get(
        "contrarian_claim"
    )
    confidence = getattr(result, "confidence", None) or result.get("confidence")
    evidence = getattr(result, "evidence_chunks", None) or result.get(
        "evidence_chunks"
    )

    assert claim is not None and "NOT" in claim.upper()
    assert confidence is not None and 0.0 <= float(confidence) <= 1.0
    assert evidence is not None and len(evidence) >= 1

    written = mock_mongo["research_intelligence_contrarian"]
    assert len(written) == 1
    rec = written[0]
    assert rec["doc_id"] == stub_contrarian_doc.document_id
    assert rec["indicator_id"] in stub_contrarian_doc.indicators
    assert "contrarian_claim" in rec
    assert "evidence_chunks" in rec
    assert "confidence" in rec
    assert "created_at" in rec
