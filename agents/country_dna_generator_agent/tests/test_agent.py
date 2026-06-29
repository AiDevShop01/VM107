"""Phase 96 Plan 05 — CountryDnaGenerator unit tests (REQ-96-4).

Hybrid Neo4j + Qdrant pipeline tests. All Qdrant + graph access is mocked.
The tests assert STRUCTURE (5-10 tags, provenance non-empty, confidence
strict bounds, country-dependent output) — not LLM-emitted text quality.

Fixtures emulate three countries with different structural signatures:

* US — services-led + reserve-currency + consumer-driven + financial-sector + export-driven
* SA — oil-export-dependent + commodity-exporter + manufacturing-led-light
* CH — financial-sector-hub + central-bank-independent + services-led
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from contracts.economic_intelligence.economic_dna_tag import EconomicDnaTag


# ---------------------------------------------------------------------------
# Mock builders — Qdrant / Graph tools
# ---------------------------------------------------------------------------


def _qdrant_hit(score: float, section_id: int, section_type: str = "ECONOMY"):
    """Build a MagicMock hit object that walks like the tool's CountryHit dict."""
    return MagicMock(
        score=score,
        section_id=section_id,
        section_type=section_type,
    )


class _StubQdrantTool:
    """Per-template Qdrant stub. Returns hits keyed by query phrases.

    The agent calls ``self.qdrant.run(query=..., section_filter=..., country=...)``
    on each STRUCTURAL_QUERY_TEMPLATE. We map characteristic substrings of
    each template's query to a top-1 score so we can drive different
    country profiles deterministically.
    """

    def __init__(self, score_map: dict[str, float]):
        self.score_map = score_map
        self.call_log: list[dict] = []

    def run(self, *, query: str, section_filter: str = "", country: str = ""):
        self.call_log.append(
            {"query": query, "section_filter": section_filter, "country": country}
        )
        # Walk the score_map and return the first match (case-insensitive contains).
        q_lower = query.lower()
        for needle, score in self.score_map.items():
            if needle.lower() in q_lower:
                # Section id derived from query length so each query lands on
                # a stable but distinct synthetic section row.
                return [_qdrant_hit(score=score, section_id=40 + len(needle) % 30)]
        return []


class _StubGraphTool:
    """Per-template graph stub. Returns synthetic Cypher path strings.

    The agent calls ``self.graph.run_template(name, iso_alpha2=..., depth=...)``.
    By default we return one or two path objects with a ``signature`` attribute
    that the agent serialises into ``provenance_graph_paths``.
    """

    def __init__(self, paths_per_call: int = 1):
        self.paths_per_call = paths_per_call

    def run_template(self, name: str, **kwargs):
        iso = kwargs.get("iso_alpha2", "??")
        out = []
        for i in range(self.paths_per_call):
            out.append(
                MagicMock(
                    signature=f"({iso}:Country)-[:REL_{i}]->(Target{i})"
                )
            )
        return out


# ---------------------------------------------------------------------------
# Country-specific score maps (drives the hybrid pipeline differentiation)
# ---------------------------------------------------------------------------


_US_SCORES = {
    "reserve currency": 0.92,
    "services sector": 0.88,
    "household consumption": 0.81,
    "exports as percentage": 0.66,
    "international banking": 0.72,
    "independent central bank": 0.68,
    "manufacturing and industrial production": 0.62,  # weak US match
}

_SA_SCORES = {
    "petroleum exports": 0.94,
    "raw commodities": 0.86,
    "majority of its energy consumption": 0.0,  # imports = no, SA exports
    "young working-age population": 0.71,
}

_CH_SCORES = {
    "international banking": 0.91,
    "services sector": 0.74,
    "independent central bank": 0.86,
    "majority of its energy consumption": 0.62,
    "aging society": 0.65,
}


# ---------------------------------------------------------------------------
# Env fixture — keep tests isolated from real Qdrant/Neo4j
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://stub:7687")
    monkeypatch.setenv("QDRANT_URL", "http://stub:6333")


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


def test_invoke_returns_between_5_and_10_tags():
    """REQ-96-4 floor/ceiling: 5..10 tags returned for US."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    tags = agent.invoke("US", {"name": "United States"})
    assert 1 <= len(tags) <= 10, f"got {len(tags)} tags (need 1..10); tags={tags!r}"
    # US should land at least 5 confirmed tags (score map has 5+ strong hits).
    assert len(tags) >= 5, f"US should land 5+ tags; got {len(tags)}"


def test_each_tag_carries_both_provenances():
    """REQ-96-4: every tag has non-empty section_ids AND graph_paths."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    tags = agent.invoke("US", {})
    assert tags, "must return at least one tag for US fixture"
    for tag in tags:
        assert isinstance(tag, EconomicDnaTag)
        assert len(tag.provenance_sections) >= 1, (
            f"tag {tag.tag_id} missing provenance_sections"
        )
        assert len(tag.provenance_graph_paths) >= 1, (
            f"tag {tag.tag_id} missing provenance_graph_paths"
        )


def test_confidence_in_strict_open_unit_interval():
    """Confidence must be in (0,1) — never 0.0, never 1.0 for non-trivial tags."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    tags = agent.invoke("US", {})
    for tag in tags:
        assert 0.0 < tag.confidence < 1.0, (
            f"tag {tag.tag_id} confidence={tag.confidence} outside (0,1)"
        )


def test_us_emits_baseline_phase_94_07_tags():
    """Phase 94-07 floor: US must keep reserve-currency / services-led / consumer-driven."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    tag_ids = {t.tag_id for t in agent.invoke("US", {})}
    assert "reserve-currency-issuer" in tag_ids
    assert "services-led" in tag_ids
    assert "consumer-driven" in tag_ids


def test_different_countries_get_different_tags():
    """Agent is not a constant function — SA vs CH differ structurally."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    sa_agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_SA_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    ch_agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_CH_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    sa_tags = {t.tag_id for t in sa_agent.invoke("SA", {})}
    ch_tags = {t.tag_id for t in ch_agent.invoke("CH", {})}

    assert sa_tags, "SA must emit at least one tag"
    assert ch_tags, "CH must emit at least one tag"
    assert "oil-export-dependent" in sa_tags, f"SA tags: {sa_tags}"
    assert "financial-sector-hub" in ch_tags, f"CH tags: {ch_tags}"
    assert sa_tags != ch_tags, "SA and CH must produce different DNA tags"


def test_env_var_fail_fast(monkeypatch):
    """NEO4J_URI / QDRANT_URL missing → from_env constructor must raise."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    with pytest.raises(KeyError):
        CountryDnaGenerator.from_env()


def test_graph_failure_degrades_softly():
    """If graph_tool throws, agent skips that tag — never crashes."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    crashing_graph = MagicMock()
    crashing_graph.run_template.side_effect = RuntimeError("neo4j down")
    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=crashing_graph,
    )
    # Must NOT raise.
    tags = agent.invoke("US", {})
    # Tags without graph confirmation are dropped → could be empty list.
    assert isinstance(tags, list)


def test_emits_country_dna_tag_recomputed_event():
    """REQ-96-11: agent emits country_dna_tag_recomputed event after invoke."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    emitter = MagicMock()
    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
        event_emitter=emitter,
    )
    tags = agent.invoke("US", {})
    assert emitter.emit.called, "event_emitter.emit was not invoked"
    call_args = emitter.emit.call_args
    # Event_type must be the registered one (Plan 04).
    assert call_args.kwargs.get("event_type") == "country_dna_tag_recomputed" or (
        call_args.args and call_args.args[0] == "country_dna_tag_recomputed"
    )
    # Payload should include iso + tag_count.
    payload = call_args.kwargs.get("payload") or (
        call_args.args[1] if len(call_args.args) >= 2 else {}
    )
    assert payload.get("iso_alpha2") == "US"
    assert payload.get("tag_count") == len(tags)


def test_idempotent_for_unchanged_profile():
    """Same fixture in → same tag set out (deterministic floor)."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    run_a = {t.tag_id for t in agent.invoke("US", {})}
    # Fresh agent + fresh stubs → same outcome.
    agent_b = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    run_b = {t.tag_id for t in agent_b.invoke("US", {})}
    assert run_a == run_b, f"non-idempotent: {run_a ^ run_b}"


def test_tags_sorted_by_confidence_desc():
    """Output cap of 10 must keep the highest-confidence tags."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrantTool(_US_SCORES),
        graph_tool=_StubGraphTool(paths_per_call=2),
    )
    tags = agent.invoke("US", {})
    if len(tags) >= 2:
        confidences = [t.confidence for t in tags]
        assert confidences == sorted(confidences, reverse=True), (
            f"tags not sorted by confidence desc: {confidences}"
        )
