"""Phase 92 Plan 05 — Wave 0 RED test for CitationAgent.

Asserts:
- CitationAgent extracts at least one citation with a valid DOI from a doc
  containing real DOI references.
- MongoDB write to `research_intelligence_citations` asserted.

RED until Task 2 ships VM107/agents/research/citation_agent.py.
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
def stub_doc_with_dois() -> _StubResearchDoc:
    return _StubResearchDoc(
        document_id="doc-nber-w12345",
        indicators=["CPIAUCSL"],
        tier=3,
        title="On the Persistence of Inflation",
        body=(
            "Following the analysis of Smith (2024) [10.1257/aer.20231234] and "
            "Jones (2023) at https://doi.org/10.3386/w98765, we estimate that "
            "the half-life of an inflation shock is approximately 18 months. "
            "See also Lee et al. (2022), doi:10.1093/qje/qjac001."
        ),
    )


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


def test_citation_agent_extracts_dois_via_regex(stub_doc_with_dois, mock_mongo):
    """RED until Task 2."""
    from agents.research.citation_agent import CitationAgent  # noqa: E501

    agent = CitationAgent()
    result = agent.process(stub_doc_with_dois)
    citations = (
        getattr(result, "citations", None) or result.get("citations")
    )
    assert citations is not None and len(citations) >= 1, (
        f"expected >= 1 citation, got {citations!r}"
    )

    # At least one DOI matches the canonical regex shape
    import re as _re

    DOI_RE = _re.compile(r"^10\.\d{4,9}/[\w\.\-_;\(\)/:]+$", _re.IGNORECASE)
    has_valid = any(DOI_RE.match(c.get("doi", "")) for c in citations)
    assert has_valid, f"no DOI matched the canonical regex: {citations}"

    written = mock_mongo["research_intelligence_citations"]
    assert len(written) == 1
    rec = written[0]
    assert rec["doc_id"] == stub_doc_with_dois.document_id
    assert isinstance(rec["citations"], list)
    assert len(rec["citations"]) >= 1
    assert "created_at" in rec
