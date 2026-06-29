"""Phase 96 Plan 05 — Provenance-discipline tests for CountryDnaGenerator.

REQ-96-4 hard lock: every tag MUST carry both provenance_sections AND
provenance_graph_paths — never one without the other. This file enforces
that discipline independently of the broader behavioural suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://stub:7687")
    monkeypatch.setenv("QDRANT_URL", "http://stub:6333")


def _hit(score: float, section_id: int):
    return MagicMock(score=score, section_id=section_id, section_type="ECONOMY")


def _qdrant_that_matches_everything():
    """Qdrant stub returning a passing hit for every query the agent calls."""

    q = MagicMock()

    def _run(*, query: str, section_filter: str = "", country: str = ""):
        # Stable section id derived from query hash so each tag lands on a
        # distinct synthetic section row.
        return [_hit(score=0.85, section_id=100 + len(query) % 50)]

    q.run = _run
    return q


def _graph_that_returns_paths(n: int = 2):
    g = MagicMock()
    g.run_template.return_value = [
        MagicMock(signature=f"(X:Country)-[:REL_{i}]->(Y{i})") for i in range(n)
    ]
    return g


def _graph_that_returns_empty():
    g = MagicMock()
    g.run_template.return_value = []
    return g


def test_no_tag_emitted_without_both_provenances():
    """A tag must have BOTH non-empty provenance_sections AND graph_paths."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_qdrant_that_matches_everything(),
        graph_tool=_graph_that_returns_paths(),
    )
    tags = agent.invoke("US", {})
    for tag in tags:
        assert len(tag.provenance_sections) > 0, (
            f"tag {tag.tag_id} has empty provenance_sections"
        )
        assert len(tag.provenance_graph_paths) > 0, (
            f"tag {tag.tag_id} has empty provenance_graph_paths"
        )


def test_no_graph_paths_means_no_tag():
    """When graph confirmation returns zero paths, tag is NOT emitted."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_qdrant_that_matches_everything(),
        graph_tool=_graph_that_returns_empty(),
    )
    tags = agent.invoke("US", {})
    # No graph confirmation → agent must drop every candidate.
    assert tags == [], (
        f"agent emitted tags without graph confirmation: {[t.tag_id for t in tags]}"
    )


def test_provenance_sections_are_ints():
    """provenance_sections values must be int (matches CountryProfileSection.id)."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_qdrant_that_matches_everything(),
        graph_tool=_graph_that_returns_paths(),
    )
    tags = agent.invoke("US", {})
    for tag in tags:
        for sid in tag.provenance_sections:
            assert isinstance(sid, int), (
                f"tag {tag.tag_id} carries non-int section id {sid!r}"
            )


def test_provenance_graph_paths_are_strings():
    """provenance_graph_paths values must be Cypher-style strings."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_qdrant_that_matches_everything(),
        graph_tool=_graph_that_returns_paths(),
    )
    tags = agent.invoke("US", {})
    for tag in tags:
        for p in tag.provenance_graph_paths:
            assert isinstance(p, str), (
                f"tag {tag.tag_id} carries non-str graph path {p!r}"
            )
            assert p, f"tag {tag.tag_id} carries empty graph path"


def test_provenance_section_ids_capped():
    """provenance_sections cap matches design — at most 3 per tag (top-3 hits)."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_qdrant_that_matches_everything(),
        graph_tool=_graph_that_returns_paths(n=5),
    )
    tags = agent.invoke("US", {})
    for tag in tags:
        assert len(tag.provenance_sections) <= 3
        assert len(tag.provenance_graph_paths) <= 3
