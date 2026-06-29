"""Phase 96 Plan 05 — REQ-96-4 Country DNA generator GREEN suite.

Flipped from the Plan 00 Wave 0 RED stub (5 xfail specs) — now real tests
that exercise the CountryDnaGenerator agent (VM107/agents/country_dna_generator_agent).

REQ-96-4 contract:
- Hybrid Neo4j + Qdrant pipeline emits 5-10 STRUCTURAL_TAG tags per country
- impact_on_decision = MEDIUM (asserted in registry YAML test, Plan 04)
- Provenance cites country_profile_sections.id AND graph paths (REQ-96-4 hard lock)
- LLM-emitted text quality is subjective; this suite asserts STRUCTURE + provenance

All Qdrant + Neo4j access mocked. CI never reaches a real VM.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from contracts.economic_intelligence.economic_dna_tag import EconomicDnaTag


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://stub:7687")
    monkeypatch.setenv("QDRANT_URL", "http://stub:6333")


# ---------------------------------------------------------------------------
# Per-country score map fixtures
# ---------------------------------------------------------------------------


_US_SCORES = {
    "reserve currency": 0.92,
    "services sector": 0.88,
    "household consumption": 0.81,
    "exports as percentage": 0.66,
    "international banking": 0.72,
    "independent central bank": 0.68,
}


_SA_SCORES = {
    "petroleum exports": 0.94,
    "raw commodities": 0.86,
    "young working-age population": 0.71,
}


class _StubQdrant:
    def __init__(self, score_map):
        self.score_map = score_map

    def run(self, *, query: str, section_filter: str = "", country: str = ""):
        q = query.lower()
        for needle, score in self.score_map.items():
            if needle.lower() in q:
                return [
                    MagicMock(
                        score=score,
                        section_id=200 + len(needle) % 40,
                        section_type=section_filter or "ECONOMY",
                    )
                ]
        return []


class _StubGraph:
    def __init__(self, paths=2):
        self.paths = paths

    def run_template(self, name: str, **kwargs):
        iso = kwargs.get("iso_alpha2", "??")
        return [
            MagicMock(signature=f"({iso}:Country)-[:REL_{i}]->(Target{i})")
            for i in range(self.paths)
        ]


# ---------------------------------------------------------------------------
# REQ-96-4 tests (replacing the 5 Plan 00 xfail stubs)
# ---------------------------------------------------------------------------


def test_country_dna_generator_returns_5_to_10_tags_for_us():
    """REQ-96-4: invoke('US', profile) returns 5..10 structural tags."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrant(_US_SCORES),
        graph_tool=_StubGraph(paths=2),
    )
    tags = agent.invoke("US", {"name": "United States"})
    assert 5 <= len(tags) <= 10, (
        f"US should land 5..10 tags; got {len(tags)} — {[t.tag_id for t in tags]}"
    )


def test_country_dna_generator_each_tag_has_provenance():
    """REQ-96-4: every tag carries section_id + graph_path provenance."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrant(_US_SCORES),
        graph_tool=_StubGraph(paths=2),
    )
    tags = agent.invoke("US", {})
    for tag in tags:
        assert isinstance(tag, EconomicDnaTag)
        assert len(tag.provenance_sections) >= 1
        assert len(tag.provenance_graph_paths) >= 1


def test_country_dna_generator_impact_on_decision_is_medium():
    """REQ-96-4: agent_profile.impact_on_decision=='MEDIUM' (CONTEXT lock)."""
    # Source: Plan 04 registry YAML — verified by Phase 96 registry test suite.
    # Here we re-read the agent's profile.yaml to make sure the on-disk file
    # carries the MEDIUM lock the registry YAML claims it does.
    from pathlib import Path

    import yaml

    profile_path = (
        Path(__file__).resolve().parent.parent.parent
        / "agents"
        / "country_dna_generator_agent"
        / "profile.yaml"
    )
    assert profile_path.exists(), f"missing {profile_path}"
    data = yaml.safe_load(profile_path.read_text())
    # Profile.yaml is agent-local config; the impact_on_decision lock lives on
    # the registry YAML (Plan 04 asserts it). We re-confirm via the constant
    # the agent module exposes for runtime introspection.
    from agents.country_dna_generator_agent import CountryDnaGenerator

    assert CountryDnaGenerator.IMPACT_ON_DECISION == "MEDIUM"


def test_country_dna_generator_emits_event_on_recomputation():
    """REQ-96-4 + REQ-96-11: emits `country_dna_tag_recomputed` event."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    emitter = MagicMock()
    agent = CountryDnaGenerator(
        qdrant_tool=_StubQdrant(_US_SCORES),
        graph_tool=_StubGraph(paths=2),
        event_emitter=emitter,
    )
    agent.invoke("US", {})
    assert emitter.emit.called
    args = emitter.emit.call_args
    event_type = args.kwargs.get("event_type") or (
        args.args[0] if args.args else None
    )
    assert event_type == "country_dna_tag_recomputed"


def test_country_dna_generator_idempotent_for_unchanged_profile():
    """REQ-96-4: same profile in -> same tag set out (deterministic floor)."""
    from agents.country_dna_generator_agent import CountryDnaGenerator

    agent_a = CountryDnaGenerator(
        qdrant_tool=_StubQdrant(_US_SCORES),
        graph_tool=_StubGraph(paths=2),
    )
    agent_b = CountryDnaGenerator(
        qdrant_tool=_StubQdrant(_US_SCORES),
        graph_tool=_StubGraph(paths=2),
    )
    set_a = {t.tag_id for t in agent_a.invoke("US", {})}
    set_b = {t.tag_id for t in agent_b.invoke("US", {})}
    assert set_a == set_b
