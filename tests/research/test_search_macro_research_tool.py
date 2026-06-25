"""Phase 92 Plan 05 — Wave 0 RED tests for search_macro_research tool.

Asserts:
- Capability Registry lookup returns the search_macro_research tool YAML
  with all required fields including impact_on_decision: HIGH and the
  Phase 70.5 envelope fields (typical_confidence, expected_freshness_seconds,
  is_deterministic).
- Tool dispatch with indicator_id=CPIAUCSL returns >= 1 result whose
  indicators list includes 'CPIAUCSL'.

RED until Task 3 ships VM107/tools/search_macro_research.py +
VM107/registry/tool/search_macro_research.yaml.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.phase92


_VM107_ROOT = Path(__file__).resolve().parents[2]
_TOOL_YAML = _VM107_ROOT / "registry" / "tool" / "search_macro_research.yaml"


def test_lookup_capability_search_macro_research_yaml_exists_and_valid():
    """RED until Task 3 — tool YAML must exist with impact_on_decision."""
    assert _TOOL_YAML.exists(), (
        f"missing registry/tool/search_macro_research.yaml at {_TOOL_YAML}"
    )
    payload = yaml.safe_load(_TOOL_YAML.read_text())
    assert payload["id"] == "search_macro_research"
    assert payload["type"] == "tool"
    assert payload["status"] == "real"
    assert payload["shipped"] == 92
    assert payload["impact_on_decision"] == "HIGH"
    # Phase 70.5 envelope provenance
    assert payload.get("typical_confidence") is not None
    assert payload.get("expected_freshness_seconds") is not None
    assert payload.get("is_deterministic") is False
    # Allowed agent profiles list includes macro_investigator
    assert "vm107.macro_investigator" in payload.get("allowed_agent_profiles", [])


def test_search_macro_research_indicator_filter_returns_matching_results(monkeypatch):
    """RED until Task 3 — tool dispatch filters by indicator_id."""
    # Stub the VM101 endpoint to return a canned payload
    monkeypatch.setenv("VM101_RESEARCH_SEARCH_URL", "http://stub.invalid/search")

    class _StubResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "doc_id": "doc-fomc-01",
                        "title": "FOMC statement, June 2026",
                        "tier": 1,
                        "indicators": ["CPIAUCSL", "UNRATE"],
                        "assets": ["GOLD", "DXY"],
                        "published_at": "2026-06-17T18:00:00Z",
                        "relevant_chunks": [
                            "Inflation has eased substantially over the past year"
                        ],
                        "similarity_score": 0.91,
                    }
                ],
                "query": "consensus on cpi",
                "total_matches": 1,
            }

    class _StubAsyncClient:
        def __init__(self, *_a, **_k):
            self._kwargs = _k

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a, **_k):
            return None

        async def post(self, url: str, json=None, **_k):
            assert "stub.invalid" in url
            assert json is not None
            assert json["filters"]["linked_indicator"] == "CPIAUCSL"
            return _StubResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _StubAsyncClient, raising=True)

    from tools.search_macro_research import SearchMacroResearchTool

    import asyncio

    tool = SearchMacroResearchTool()
    resp = asyncio.run(
        tool.execute(query="consensus on cpi", indicator_id="CPIAUCSL", top_k=5)
    )
    # Response can be a Pydantic model OR dict-like — handle both
    results = getattr(resp, "results", None) or resp["results"]
    assert len(results) >= 1
    r0 = results[0]
    ind = getattr(r0, "indicators", None) or r0["indicators"]
    assert "CPIAUCSL" in ind
