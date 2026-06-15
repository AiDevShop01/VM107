"""Phase 87 Wave 2 — agent walk-step unit tests.

Validates that ``MacroTransmissionAnalyst.run()``:
  - calls the walker tool with the indicator_id from the release event
  - calls the episodic_memory stub to query relevant memories
  - calls the narration skill to produce a hop-by-hop narrative
  - persists envelope + B1 + macro_transmission_analysis row
  - publishes ``macro.transmission.<indicator_id>.updated`` WS topic
  - handles the empty-chain edge case gracefully (degraded fallback)

All collaborators are MagicMock — these are unit tests, NOT integration.
The on-release end-to-end test (test_transmission_analyst_on_release.py) is
the integration surface and exercises the testcontainers Neo4j.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from agents.macro_transmission_analyst.agent import MacroTransmissionAnalyst
from agents.macro_transmission_analyst.skill_transmission_narration import (
    TransmissionNarrationSkill,
)
from tools.neo4j_macro_graph_walker import Hop

pytestmark = pytest.mark.phase_87


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_narrative() -> str:
    """LLM response that passes BOTH hard assertions on first attempt.

    Per agent profile YAML:
      - narrative_strength_for_3_hops:  regex 'strength\\s*[=:]\\s*-?\\d', >=3 matches
      - narrative_period:               regex '\\d{4}-\\d{2}-\\d{2}/\\d{4}-\\d{2}-\\d{2}', >=1 match
    """
    return (
        "CPI rose with strength=0.40 over period 2021-01-01/2026-01-01 "
        "[ref:edge:CPIAUCSL:UNRATE]. UNRATE responded with strength=-0.55 "
        "over 2021-01-01/2026-01-01 [ref:edge:UNRATE:GDP]. GDP downstream "
        "with strength=0.45 over 2021-01-01/2026-01-01 [ref:edge:GDP:CPIAUCSL]."
    )


def _make_agent(walker_hops, llm_response=None):
    walker = MagicMock()
    walker.walk.return_value = walker_hops

    episodic_memory = MagicMock()
    episodic_memory.query.return_value = {
        "memories_retrieved": [],
        "confidence": 0.0,
        "cache_hit": False,
    }

    llm_router = MagicMock()
    llm_router.complete.return_value = llm_response or _valid_narrative()
    narration = TransmissionNarrationSkill(llm_router=llm_router)

    envelope_repo = MagicMock()
    envelope_repo.persist.return_value = uuid.uuid4()

    b1_repo = MagicMock()
    b1_repo.persist.return_value = uuid.uuid4()

    persist = MagicMock()
    persist.create.return_value = uuid.uuid4()

    ws = MagicMock()

    agent = MacroTransmissionAnalyst(
        walker=walker,
        episodic_memory_service=episodic_memory,
        narration_skill=narration,
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )
    return agent, persist, ws, envelope_repo, b1_repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_three_hop_chain_persists_envelope(release_event_factory):
    """Happy path: 3-hop chain → narrative → envelope + B1 + WS publish."""
    hops = [
        Hop("CPIAUCSL", "UNRATE", "AFFECTS", 0.40, 0.70, 60, "2021-01-01/2026-01-01", 0),
        Hop("CPIAUCSL", "GDP", "AFFECTS", 0.28, 0.62, 60, "2021-01-01/2026-01-01", 1),
        Hop("CPIAUCSL", "XAUUSD", "DRIVES", 0.41, 0.65, 240, "2018-01-01/2026-01-01", None),
    ]
    agent, persist, ws, envelope_repo, b1_repo = _make_agent(hops)

    event = release_event_factory(indicator_id="CPIAUCSL")
    result = agent.run(event)

    assert len(result.chain) == 3
    assert not result.degraded
    persist.create.assert_called_once()
    envelope_repo.persist.assert_called_once()
    b1_repo.persist.assert_called_once()
    ws.publish.assert_called_once_with(
        "macro.transmission.CPIAUCSL.updated", payload=None
    )


def test_walker_called_with_event_indicator_id(release_event_factory):
    """Walker MUST receive the indicator_id straight from the release event."""
    hops = [
        Hop("UNRATE", "GDP", "AFFECTS", -0.55, 0.74, 60, "2021-01-01/2026-01-01", 0),
        Hop("UNRATE", "CPIAUCSL", "AFFECTS", -0.32, 0.61, 60, "2021-01-01/2026-01-01", 1),
        Hop("UNRATE", "DXY", "DRIVES", 0.39, 0.66, 240, "2018-01-01/2026-01-01", None),
    ]
    agent, _, _, _, _ = _make_agent(hops)
    event = release_event_factory(indicator_id="UNRATE")
    agent.run(event)
    agent._walker.walk.assert_called_once_with("UNRATE", max_hops=5)


def test_empty_chain_does_not_crash(release_event_factory):
    """Empty Neo4j walk → agent still persists with degraded fallback.

    Per plan behaviour spec: 'given a malformed Neo4j (no edges) the agent
    emits a chain_empty outcome (does not crash)' — and per the deviation
    spec the envelope is persisted with degraded=True.
    """
    agent, persist, ws, envelope_repo, _ = _make_agent([])
    event = release_event_factory(indicator_id="UNKNOWN")
    result = agent.run(event)

    assert result.chain == []
    assert result.degraded is True
    persist.create.assert_called_once()
    envelope_repo.persist.assert_called_once()


def test_citation_grammar_for_three_hops(release_event_factory):
    """Narrative must include [ref:edge:<src>:<dst>] for >=3 hops.

    The valid narrative fixture used by _make_agent includes 3 citations
    so result.narrative_text MUST contain three [ref:edge:...] tokens.
    """
    hops = [
        Hop("CPIAUCSL", "UNRATE", "AFFECTS", 0.40, 0.70, 60, "2021-01-01/2026-01-01", 0),
        Hop("CPIAUCSL", "GDP", "AFFECTS", 0.28, 0.62, 60, "2021-01-01/2026-01-01", 1),
        Hop("CPIAUCSL", "XAUUSD", "DRIVES", 0.41, 0.65, 240, "2018-01-01/2026-01-01", None),
    ]
    agent, _, _, _, _ = _make_agent(hops)
    result = agent.run(release_event_factory())
    citation_count = result.narrative_text.count("[ref:edge:")
    assert citation_count >= 3, (
        f"narrative must cite >=3 hops with [ref:edge:...]; got {citation_count}"
    )
