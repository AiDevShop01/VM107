"""Phase 92 Plan 05 — Wave 0 RED test for macro_investigator + search_macro_research integration.

Asserts:
- vm107.macro_investigator.yaml has `search_macro_research` in allowed_tools
  AND it is NOT in denied_tools (post-LD-92-8 flip).
- A simulated indicator-scoped Q invokes the tool ≥1 time via the
  dispatch path and the canned response is consumed by the agent shape.

RED until Task 3 flips the profile.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.phase92


_VM107_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_YAML = (
    _VM107_ROOT / "registry" / "agent_profile" / "vm107.macro_investigator.yaml"
)


def test_macro_investigator_has_search_macro_research_in_allowed_tools():
    """RED until Task 3 — profile flip from denied→allowed."""
    assert _PROFILE_YAML.exists(), f"missing {_PROFILE_YAML}"
    payload = yaml.safe_load(_PROFILE_YAML.read_text())
    allowed = payload.get("allowed_tools", []) or []
    denied = payload.get("denied_tools", []) or []
    assert "search_macro_research" in allowed, (
        "search_macro_research must be in allowed_tools post-LD-92-8 flip; "
        f"got allowed={allowed}"
    )
    assert "search_macro_research" not in denied, (
        "search_macro_research must be removed from denied_tools post-LD-92-8 "
        f"flip; got denied={denied}"
    )


def test_indicator_scoped_question_invokes_search_macro_research(monkeypatch):
    """Simulate the dispatch path: dispatch_tool('search_macro_research', ...) returns
    canned ResearchDocument citations.

    RED until Task 3 ships VM107/tools/search_macro_research.py.
    """
    monkeypatch.setenv("VM101_RESEARCH_SEARCH_URL", "http://stub.invalid/search")

    canned = {
        "results": [
            {
                "doc_id": "doc-fomc-01",
                "title": "FOMC statement, June 2026",
                "tier": 1,
                "indicators": ["CPIAUCSL"],
                "assets": ["GOLD"],
                "published_at": "2026-06-17T18:00:00Z",
                "relevant_chunks": ["Inflation has eased substantially"],
                "similarity_score": 0.93,
            }
        ],
        "query": "What is the consensus on CPI?",
        "total_matches": 1,
    }

    class _StubResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return canned

    class _StubAsyncClient:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a, **_k):
            return None

        async def post(self, url, json=None, **_k):
            return _StubResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _StubAsyncClient, raising=True)

    from tools.search_macro_research import SearchMacroResearchTool

    import asyncio

    tool = SearchMacroResearchTool()
    resp = asyncio.run(
        tool.execute(
            query="What is the consensus on CPI?",
            indicator_id="CPIAUCSL",
            top_k=5,
        )
    )
    results = getattr(resp, "results", None) or resp["results"]
    assert len(results) >= 1
    r0 = results[0]
    title = getattr(r0, "title", None) or r0["title"]
    assert "FOMC" in title
