"""Phase 92 Plan 05 — Wave 0 RED test for SummarisationAgent.

Asserts:
- SummarisationAgent.process(research_doc) returns a SummaryResult with
  a 3-bullet executive summary + key_findings list (>= 1 item)
- The result is persisted to MongoDB via storage.write_summary

This test is RED until Task 2 ships VM107/agents/research/summarisation_agent.py
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
def stub_research_doc() -> _StubResearchDoc:
    return _StubResearchDoc(
        document_id="doc-fomc-2026-06-17",
        indicators=["CPIAUCSL", "UNRATE"],
        tier=1,
        title="FOMC statement, June 2026",
        body=(
            "Inflation has eased substantially over the past year but remains "
            "above the Committee's 2 percent objective. Labour market conditions "
            "have continued to soften. The Committee will continue to assess "
            "additional information and its implications for monetary policy."
        ),
    )


@pytest.fixture
def mock_llm(monkeypatch):
    """Patch the LLM call to return a deterministic 3-bullet response."""
    canned = (
        "- Inflation continues to ease but remains above 2% target.\n"
        "- Labour market conditions softening.\n"
        "- Committee data-dependent on policy path.\n"
        "KEY_FINDINGS:\n"
        "- inflation_above_target\n"
        "- labour_market_softening\n"
    )

    def _fake_call(prompt: str) -> str:
        assert "FOMC" in prompt or "summary" in prompt.lower() or "summari" in prompt.lower()
        return canned

    # Patch both the agent's call site and the service module directly
    monkeypatch.setattr("services.llm_client.call_llm", _fake_call, raising=False)
    return _fake_call


@pytest.fixture
def mock_mongo(monkeypatch):
    """In-memory MongoDB replacement — captures writes for assertion."""
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
                inserted_id = doc.get("_id", f"id-{len(storage[self._name])}")

            return _R()

        def find(self, *_a, **_k):
            return list(storage[self._name])

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


def test_summarisation_agent_writes_mongo_with_three_bullets_and_findings(
    stub_research_doc, mock_llm, mock_mongo
):
    """Wave 0 RED — RED until Task 2 ships summarisation_agent.py."""
    from agents.research.summarisation_agent import SummarisationAgent  # noqa: E501

    agent = SummarisationAgent()
    result = agent.process(stub_research_doc)

    # Result shape
    assert result is not None
    bullets = getattr(result, "summary_bullets", None) or result.get("summary_bullets")
    findings = getattr(result, "key_findings", None) or result.get("key_findings")
    assert bullets is not None and len(bullets) == 3, (
        f"expected 3 bullets, got {bullets!r}"
    )
    assert findings is not None and len(findings) >= 1

    # MongoDB write asserted
    written = mock_mongo["research_intelligence_summaries"]
    assert len(written) == 1
    rec = written[0]
    assert rec["doc_id"] == stub_research_doc.document_id
    assert "indicator_id" in rec
    assert rec["indicator_id"] in stub_research_doc.indicators
    assert "summary" in rec
    assert "key_findings" in rec
    assert "created_at" in rec
