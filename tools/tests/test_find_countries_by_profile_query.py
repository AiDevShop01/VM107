"""Phase 96 Plan 06 Task 1 — find_countries_by_profile_query tool tests.

REQ-96-8: Qdrant cross-country semantic search tool. Mirrors the GraphSearchTool
pattern (VM107/tools/graph/graph_search_tool.py) — ContractTool subclass with
Pydantic request/response validation + graceful Qdrant-down degradation.

Covered behaviors (mapped to plan must_haves):
- Dedup-by-country: same country appears at most once in results, highest score wins
- section_evidence aggregation: up to 3 sections per country with narrative snippets ≤ 200 chars
- section_filter passes Qdrant Filter(must=[FieldCondition(...)])
- country_filter passes Filter(must=[FieldCondition(MatchAny)])
- min_score gates returned hits
- Empty query → Pydantic ValidationError (min_length=3)
- Qdrant URL unset → fail-fast at construction (KeyError, no os.getenv default)
- Qdrant exception → empty countries + structured log + non-zero query_hash + latency_ms
- Structured log includes query_hash + top_k + latency_ms + result_count
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _hit(score: float, iso: str, name: str, section_type: str, section_id: int, narrative: str):
    """Build a MagicMock simulating a qdrant_client search hit."""
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


def _mock_qdrant_with_us_gb_jp():
    c = MagicMock()
    hits = [
        _hit(0.92, "US", "United States", "ECONOMY", 42, "Reserve currency issuer with deep capital markets and floating exchange rate"),
        _hit(0.78, "GB", "United Kingdom", "ECONOMY", 53, "Financial sector dominance, post-Brexit trade realignment"),
        _hit(0.66, "US", "United States", "ENERGY", 44, "Major oil producer, net energy exporter since 2019 shale boom"),
        _hit(0.55, "JP", "Japan", "ECONOMY", 63, "High public debt to GDP, demographic headwind, yen carry-trade anchor"),
    ]
    c.search.return_value = hits
    return c


def _mock_embedder(dim: int = 768):
    """sync embedder returning a fixed vector — matches the .embed(str) -> list[float] contract."""
    e = MagicMock()
    e.embed.return_value = [0.1] * dim
    e.MODEL_NAME = "test-embedder-mock"
    e.VECTOR_DIM = dim
    return e


@pytest.fixture(autouse=True)
def _set_qdrant_url(monkeypatch):
    """Default env: QDRANT_URL present (per plan: env-driven, no fallback)."""
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-test:6333")
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# Tests — behavioral contract
# ---------------------------------------------------------------------------

def test_returns_dedup_by_country():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    tool = FindCountriesByProfileQueryTool(
        qdrant_client=_mock_qdrant_with_us_gb_jp(),
        embedder=_mock_embedder(),
    )
    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=5))

    isos = [c.iso_alpha2 for c in resp.countries]
    assert len(isos) == len(set(isos)), f"Duplicate country ISOs in result: {isos}"
    # 3 distinct countries in mock fixture (US appears twice, dedup → once)
    assert len(resp.countries) == 3


def test_us_aggregates_multi_section_evidence():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    tool = FindCountriesByProfileQueryTool(
        qdrant_client=_mock_qdrant_with_us_gb_jp(),
        embedder=_mock_embedder(),
    )
    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=5))

    us = next(c for c in resp.countries if c.iso_alpha2 == "US")
    # US has 2 hits in mock (ECONOMY + ENERGY) — both kept as section_evidence
    assert len(us.section_evidence) == 2
    section_types = {ev["section_type"] for ev in us.section_evidence}
    assert section_types == {"ECONOMY", "ENERGY"}


def test_section_evidence_truncates_narrative_to_200_chars():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = MagicMock()
    long_narrative = "x" * 1000
    qdr.search.return_value = [_hit(0.9, "US", "United States", "ECONOMY", 1, long_narrative)]
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())

    resp = tool.run(FindCountriesByProfileRequest(query="long narrative test"))
    assert len(resp.countries) == 1
    assert len(resp.countries[0].section_evidence[0]["narrative_snippet"]) == 200


def test_section_filter_passes_qdrant_field_condition():
    """section_filter='ECONOMY' must be wired into Qdrant Filter(must=[FieldCondition(...)])."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = _mock_qdrant_with_us_gb_jp()
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())
    tool.run(FindCountriesByProfileRequest(query="reserve currency", section_filter="ECONOMY", top_k=5))

    call_kwargs = qdr.search.call_args.kwargs
    assert call_kwargs["query_filter"] is not None, "section_filter must produce a non-None Filter"
    qfilter = call_kwargs["query_filter"]
    # Filter has `must` attribute (list of conditions) when constructed via Filter(must=[...])
    assert qfilter.must is not None and len(qfilter.must) >= 1
    # First condition is a FieldCondition on section_type
    cond = qfilter.must[0]
    assert cond.key == "section_type"
    assert cond.match.value == "ECONOMY"


def test_no_filter_when_neither_section_nor_country_filter_given():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = _mock_qdrant_with_us_gb_jp()
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())
    tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=5))

    assert qdr.search.call_args.kwargs["query_filter"] is None


def test_country_filter_passes_match_any():
    """country_filter=['US','GB'] must produce Filter with MatchAny on country_iso."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = _mock_qdrant_with_us_gb_jp()
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())
    tool.run(FindCountriesByProfileRequest(query="reserve currency", country_filter=["US", "GB"], top_k=5))

    call_kwargs = qdr.search.call_args.kwargs
    qfilter = call_kwargs["query_filter"]
    assert qfilter is not None
    # First condition should be country_iso MatchAny
    cond = next(c for c in qfilter.must if c.key == "country_iso")
    # MatchAny stores the list under `.any`
    assert cond.match.any == ["US", "GB"]


def test_min_score_filters_below_threshold():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    tool = FindCountriesByProfileQueryTool(
        qdrant_client=_mock_qdrant_with_us_gb_jp(),
        embedder=_mock_embedder(),
    )
    # min_score=0.7 → only US (0.92) + GB (0.78) survive; JP (0.55) drops
    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency", min_score=0.7, top_k=5))

    assert all(c.score >= 0.7 for c in resp.countries)
    isos = {c.iso_alpha2 for c in resp.countries}
    assert "JP" not in isos


def test_top_k_caps_result_count():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    tool = FindCountriesByProfileQueryTool(
        qdrant_client=_mock_qdrant_with_us_gb_jp(),
        embedder=_mock_embedder(),
    )
    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=2))

    assert len(resp.countries) == 2
    # Highest-scoring country (US) first
    assert resp.countries[0].iso_alpha2 == "US"


def test_results_sorted_by_score_desc():
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    tool = FindCountriesByProfileQueryTool(
        qdrant_client=_mock_qdrant_with_us_gb_jp(),
        embedder=_mock_embedder(),
    )
    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=5))

    scores = [c.score for c in resp.countries]
    assert scores == sorted(scores, reverse=True)


def test_empty_query_validation_error():
    """Pydantic min_length=3 on query field rejects empty/short strings."""
    from tools.find_countries_by_profile_query import FindCountriesByProfileRequest

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FindCountriesByProfileRequest(query="")
    with pytest.raises(ValidationError):
        FindCountriesByProfileRequest(query="ab")  # min_length=3


def test_env_qdrant_url_missing_raises_keyerror(monkeypatch):
    """No os.getenv('X', 'default') fallback — missing QDRANT_URL → KeyError at construction."""
    from tools.find_countries_by_profile_query import FindCountriesByProfileQueryTool

    monkeypatch.delenv("QDRANT_URL", raising=False)
    with pytest.raises(KeyError):
        FindCountriesByProfileQueryTool()


def test_qdrant_search_failure_returns_empty_not_raise():
    """Graceful degradation: Qdrant exception → empty countries[] + error log, NOT raise."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = MagicMock()
    qdr.search.side_effect = RuntimeError("qdrant offline")
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())

    resp = tool.run(FindCountriesByProfileRequest(query="reserve currency"))
    assert resp.countries == []
    assert resp.query_hash != ""
    assert resp.latency_ms >= 0


def test_structured_log_emitted(caplog):
    """run() must emit an INFO log with query_hash + top_k + latency_ms + result_count."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    tool = FindCountriesByProfileQueryTool(
        qdrant_client=_mock_qdrant_with_us_gb_jp(),
        embedder=_mock_embedder(),
    )
    with caplog.at_level(logging.INFO, logger="tools.find_countries_by_profile_query"):
        tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=5))

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records, "Expected INFO log from run()"
    log_text = " ".join(r.getMessage() for r in info_records)
    assert "query_hash" in log_text
    assert "result_count" in log_text
    assert "latency_ms" in log_text


def test_qdrant_called_with_overscan_limit():
    """limit must be top_k * 3 (post-dedup headroom per plan)."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = _mock_qdrant_with_us_gb_jp()
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())
    tool.run(FindCountriesByProfileRequest(query="reserve currency", top_k=5))

    assert qdr.search.call_args.kwargs["limit"] == 15  # 5 * 3


def test_collection_name_is_country_profiles():
    """Tool hits the 'country_profiles' collection (per registry YAML + plan must_haves)."""
    from tools.find_countries_by_profile_query import (
        FindCountriesByProfileQueryTool,
        FindCountriesByProfileRequest,
    )

    qdr = _mock_qdrant_with_us_gb_jp()
    tool = FindCountriesByProfileQueryTool(qdrant_client=qdr, embedder=_mock_embedder())
    tool.run(FindCountriesByProfileRequest(query="reserve currency"))

    assert qdr.search.call_args.kwargs["collection_name"] == "country_profiles"
