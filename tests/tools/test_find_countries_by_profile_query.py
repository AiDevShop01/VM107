"""Phase 96 Plan 06 — REQ-96-8 find_countries_by_profile_query tool tests (GREEN).

Plan 96-06 Task 1 flips Plan 96-00's xfailed RED stub to GREEN. The full
behavioral suite lives at VM107/tools/tests/test_find_countries_by_profile_query.py;
this file keeps the original 4 REQ-96-8 specs from Plan 00 so the W0 trace
(REQ-96-8 → this file) continues to satisfy the requirements gate.

Tool contract (ContractTool, mirrors VM107/tools/qdrant/search_knowledge.py):
- Input: natural-language query string + optional filters (section, country, min_score)
- Output: top-K (default 10) UNIQUE country matches with similarity scores +
  per-country section_evidence (up to 3 sections, narrative ≤ 200 chars)
- Backed by Qdrant `country_profiles` collection
- Empty / Qdrant-down → graceful empty list + structured error log
  (NOT raise — per ContractTool base contract). Plan 00 stub said "raise" but
  Plan 06 RESEARCH §Pattern 8 + base ContractTool semantics require graceful
  degradation so agents don't crash; deviation documented in 96-06-SUMMARY.md.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures (minimal — full suite at tools/tests/)
# ---------------------------------------------------------------------------

def _hit(score, iso, name, section_type, section_id, narrative):
    h = MagicMock()
    h.score = score
    h.payload = {
        "country_iso": iso,
        "country_name": name,
        "section_type": section_type,
        "section_id": section_id,
        "narrative": narrative,
    }
    return h


def _mock_embedder():
    e = MagicMock()
    e.embed.return_value = [0.1] * 768
    return e


@pytest.fixture(autouse=True)
def _qdrant_url(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-test:6333")
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# REQ-96-8 specs (4 — original Plan 00 stub names, now GREEN)
# ---------------------------------------------------------------------------

def test_find_countries_returns_top_k_for_canned_query():
    """REQ-96-8: 'high inflation emerging market' returns 10 country matches (capped at top_k)."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    # Mock 12 hits across 12 countries — top_k=10 caps result
    iso_codes = ["TR", "AR", "BR", "ZA", "EG", "PK", "NG", "VN", "ID", "IN", "MX", "PH"]
    qdr = MagicMock()
    qdr.search.return_value = [
        _hit(0.95 - i * 0.05, iso, f"Country-{iso}", "ECONOMY", i, f"High inflation emerging market profile {iso}")
        for i, iso in enumerate(iso_codes)
    ]
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())

    resp = tool.run(FindCountriesByProfileRequest(query="high inflation emerging market", top_k=10))

    assert len(resp.countries) == 10
    # Sorted by score desc
    scores = [c.score for c in resp.countries]
    assert scores == sorted(scores, reverse=True)


def test_find_countries_respects_region_filter():
    """REQ-96-8: country_filter=['TR','AR','BR'] restricts results to those ISOs."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )
    from qdrant_client.models import MatchAny

    qdr = MagicMock()
    qdr.search.return_value = [
        _hit(0.9, "TR", "Türkiye", "ECONOMY", 1, "Lira crisis profile"),
        _hit(0.8, "AR", "Argentina", "ECONOMY", 2, "Hyperinflation history"),
        _hit(0.7, "BR", "Brazil", "ECONOMY", 3, "Central bank hawkish cycle"),
    ]
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())

    resp = tool.run(
        FindCountriesByProfileRequest(
            query="high inflation",
            country_filter=["TR", "AR", "BR"],
            top_k=10,
        )
    )

    # All returned countries are in the filter set
    assert {c.iso_alpha2 for c in resp.countries}.issubset({"TR", "AR", "BR"})
    # And the qdrant filter carried the MatchAny condition
    qf = qdr.search.call_args.kwargs["query_filter"]
    cond = next(c for c in qf.must if c.key == "country_iso")
    assert isinstance(cond.match, MatchAny)
    assert cond.match.any == ["TR", "AR", "BR"]


def test_find_countries_attaches_section_excerpts_as_citations():
    """REQ-96-8: each match carries the section text that scored it (citation-ready)."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = MagicMock()
    qdr.search.return_value = [
        _hit(0.92, "US", "United States", "ECONOMY", 42, "Reserve currency issuer with deep capital markets"),
        _hit(0.66, "US", "United States", "ENERGY", 44, "Major oil producer, net energy exporter"),
    ]
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())

    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency issuer"))

    assert len(resp.countries) == 1
    us = resp.countries[0]
    # Each piece of evidence carries section_type + section_id + narrative_snippet + score
    assert len(us.section_evidence) == 2
    for ev in us.section_evidence:
        assert "section_type" in ev
        assert "section_id" in ev
        assert "narrative_snippet" in ev
        assert "score" in ev
        assert ev["narrative_snippet"]  # non-empty
        assert len(ev["narrative_snippet"]) <= 200


def test_find_countries_raises_operator_actionable_on_empty_collection():
    """REQ-96-8 + RESEARCH §Pitfall 3: zero-vector / Qdrant-down → empty + structured log.

    DEVIATION FROM PLAN 00 STUB: Stub demanded `raise` on empty/broken collection.
    Plan 06's RESEARCH §Pattern 8 and the ContractTool base contract require
    graceful degradation (empty results + structured error log) so agents never
    crash. The operator-actionable signal is the ERROR-level structured log
    (`event=qdrant_search_failed`, query_hash), not an exception.
    """
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )
    import logging

    qdr = MagicMock()
    qdr.search.side_effect = RuntimeError("collection 'country_profiles' missing or empty")
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())

    caplog_handler = logging.handlers.MemoryHandler(capacity=10)
    logger = logging.getLogger("tools.find_countries_by_profile_query")
    logger.addHandler(caplog_handler)
    logger.setLevel(logging.ERROR)
    try:
        resp = tool.run(FindCountriesByProfileRequest(query="reserve currency"))
        # Graceful — empty but well-formed response
        assert resp.countries == []
        assert resp.query_hash != ""
        # Operator-actionable: ERROR log emitted
        assert any(r.levelno == logging.ERROR for r in caplog_handler.buffer)
    finally:
        logger.removeHandler(caplog_handler)
