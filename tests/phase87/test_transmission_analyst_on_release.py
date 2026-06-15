"""Phase 87 Wave 2 — end-to-end transmission analyst on release.

REQ-87-2: release event → envelope persisted within 60s with >=4 hops cited.
VALIDATION row 87-02-02: this is the acceptance gate for Wave 2.

Integration surface: testcontainers Neo4j seeded with the Wave-0 minimal
fixture + real Neo4jMacroGraphWalker → in-process MockTransport for the
VM100 endpoint → real MacroTransmissionAnalyst → mocked envelope_repo /
b1_repo / persist_repo / ws_publisher.

The end-to-end test does NOT stand up a full Django dev server — the
VM100 internal endpoint is exercised independently by VM100's own test
suite. This test confirms the agent-to-walker-to-Neo4j hop chain works,
which is what REQ-87-2 actually asserts.
"""
from __future__ import annotations

import pathlib
import time
import uuid
from unittest.mock import MagicMock

import httpx
import pytest

from agents.macro_transmission_analyst.agent import MacroTransmissionAnalyst
from agents.macro_transmission_analyst.skill_transmission_narration import (
    TransmissionNarrationSkill,
)
from services.macro_graph.loader import MacroGraphLoader
from tools.neo4j_macro_graph_walker import Neo4jMacroGraphWalker

pytestmark = pytest.mark.phase_87


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_LLM_NARRATIVE = (
    "CPI release rose with strength=0.40 over the evidence period "
    "2021-01-01/2026-01-01 [ref:edge:CPIAUCSL:UNRATE]. The shock then "
    "propagated to UNRATE with strength=-0.55 over 2021-01-01/2026-01-01 "
    "[ref:edge:CPIAUCSL:GDP]. Gold reacted negatively with strength=0.41 "
    "over 2018-01-01/2026-01-01 [ref:edge:CPIAUCSL:XAUUSD]. Equity "
    "downstream with strength=0.33 over 2018-01-01/2026-01-01 "
    "[ref:edge:CPIAUCSL:SPX]."
)


def _seed_graph(driver):
    """Apply the Wave-0 minimal seed to the testcontainers Neo4j driver."""
    seed_path = (
        pathlib.Path(__file__).parent / "fixtures" / "macro_graph_seed_test.yaml"
    )

    class _NullAugmenter:
        def augment_affects(self, **kwargs):
            from dataclasses import replace
            return replace(kwargs["yaml_fallback"], degraded=True)

        def augment_drives(self, **kwargs):
            from dataclasses import replace
            return replace(kwargs["yaml_fallback"], degraded=True)

    MacroGraphLoader(
        seed_yaml_path=seed_path,
        augmenter=_NullAugmenter(),
        neo4j_driver=driver,
    ).load(dry_run=False, check_schema=True)


def _build_walker(driver) -> Neo4jMacroGraphWalker:
    """httpx MockTransport handler that mimics the VM100 graph-walk endpoint."""

    def _handler(request: httpx.Request) -> httpx.Response:
        indicator_id = request.url.path.rsplit("/", 1)[-1]
        with driver.session() as session:
            rows = session.run(
                "MATCH (i:MacroIndicator {id: $id})-[r:AFFECTS]->(t:MacroIndicator) "
                "RETURN i.id AS source, t.id AS target, 'AFFECTS' AS rel, "
                "       r.strength AS strength, r.confidence AS confidence, "
                "       r.sample_size AS sample_size, "
                "       r.evidence_period AS period, "
                "       r.hop_order AS hop_order "
                "UNION "
                "MATCH (i:MacroIndicator {id: $id})-[d:DRIVES]->(a:Asset) "
                "RETURN i.id AS source, a.symbol AS target, 'DRIVES' AS rel, "
                "       d.strength AS strength, d.confidence AS confidence, "
                "       d.sample_size AS sample_size, "
                "       d.evidence_period AS period, "
                "       NULL AS hop_order",
                id=indicator_id,
            ).data()
        hops = [
            {
                "source": r["source"],
                "target": r["target"],
                "relationship_type": r["rel"],
                "strength": float(r["strength"]),
                "confidence": float(r["confidence"]),
                "sample_size": int(r["sample_size"]),
                "evidence_period": str(r["period"]),
                "hop_order": r["hop_order"],
            }
            for r in rows
        ]
        return httpx.Response(
            200, json={"indicator_id": indicator_id, "hops": hops}
        )

    walker = Neo4jMacroGraphWalker(vm100_internal_base_url="http://test")
    walker._client = httpx.Client(transport=httpx.MockTransport(_handler))
    return walker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_full_pipeline_persists_envelope_within_60s(
    neo4j_test_driver,
    release_event_factory,
    episodic_memory_stub,
):
    """REQ-87-2 acceptance: release → envelope persisted in <60s with >=4 hops.

    Wave-0 minimal seed for CPIAUCSL has 2 AFFECTS edges (→UNRATE, →GDP)
    + 2 DRIVES terminals (→XAUUSD, →SPX) = 4 hops total.
    """
    _seed_graph(neo4j_test_driver)
    walker = _build_walker(neo4j_test_driver)

    llm = MagicMock()
    llm.complete.return_value = _VALID_LLM_NARRATIVE
    narration = TransmissionNarrationSkill(llm_router=llm)

    envelope_repo = MagicMock()
    envelope_repo.persist.return_value = uuid.uuid4()
    b1_repo = MagicMock()
    b1_repo.persist.return_value = uuid.uuid4()
    persist = MagicMock()
    persist.create.return_value = uuid.uuid4()
    ws = MagicMock()

    agent = MacroTransmissionAnalyst(
        walker=walker,
        episodic_memory_service=episodic_memory_stub,
        narration_skill=narration,
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )

    event = release_event_factory(indicator_id="CPIAUCSL")
    t0 = time.monotonic()
    result = agent.run(event)
    elapsed = time.monotonic() - t0

    assert elapsed < 60.0, f"REQ-87-2: pipeline took {elapsed:.1f}s (budget 60s)"
    assert len(result.chain) >= 4, (
        f"REQ-87-2 acceptance: >=4 hops cited; got {len(result.chain)}"
    )
    assert not result.degraded
    persist.create.assert_called_once()
    envelope_repo.persist.assert_called_once()
    b1_repo.persist.assert_called_once()
    ws.publish.assert_called_once_with(
        "macro.transmission.CPIAUCSL.updated", payload=None
    )


def test_full_pipeline_emits_citation_grammar(
    neo4j_test_driver,
    release_event_factory,
    episodic_memory_stub,
):
    """Narrative MUST include [ref:edge:<src>:<dst>] for >=3 hops.

    Required by Phase 71 evidence drawer — citations resolve via the
    grammar [ref:edge:<src>:<dst>]; downstream UI cannot resolve hops
    that aren't tagged.
    """
    _seed_graph(neo4j_test_driver)
    walker = _build_walker(neo4j_test_driver)

    llm = MagicMock()
    llm.complete.return_value = _VALID_LLM_NARRATIVE
    narration = TransmissionNarrationSkill(llm_router=llm)

    envelope_repo = MagicMock(); envelope_repo.persist.return_value = uuid.uuid4()
    b1_repo = MagicMock(); b1_repo.persist.return_value = uuid.uuid4()
    persist = MagicMock(); persist.create.return_value = uuid.uuid4()
    ws = MagicMock()

    agent = MacroTransmissionAnalyst(
        walker=walker,
        episodic_memory_service=episodic_memory_stub,
        narration_skill=narration,
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )

    result = agent.run(release_event_factory(indicator_id="CPIAUCSL"))
    citation_count = result.narrative_text.count("[ref:edge:")
    assert citation_count >= 3, (
        f"narrative must include [ref:edge:...] for >=3 hops; got {citation_count}"
    )


def test_full_pipeline_includes_inline_strength_and_period(
    neo4j_test_driver,
    release_event_factory,
    episodic_memory_stub,
):
    """Narrative MUST inline strength= for >=3 hops AND >=1 ISO date range.

    This is the hard-assertion regex contract from the agent profile YAML;
    end-to-end test confirms the gate fires correctly on the real walker
    + valid LLM response (does not regress to degraded path).
    """
    import re
    _seed_graph(neo4j_test_driver)
    walker = _build_walker(neo4j_test_driver)

    llm = MagicMock()
    llm.complete.return_value = _VALID_LLM_NARRATIVE
    narration = TransmissionNarrationSkill(llm_router=llm)

    envelope_repo = MagicMock(); envelope_repo.persist.return_value = uuid.uuid4()
    b1_repo = MagicMock(); b1_repo.persist.return_value = uuid.uuid4()
    persist = MagicMock(); persist.create.return_value = uuid.uuid4()
    ws = MagicMock()

    agent = MacroTransmissionAnalyst(
        walker=walker,
        episodic_memory_service=episodic_memory_stub,
        narration_skill=narration,
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )

    result = agent.run(release_event_factory(indicator_id="CPIAUCSL"))
    strength_hits = len(re.findall(r"strength\s*[=:]\s*-?\d", result.narrative_text))
    period_hits = len(
        re.findall(r"\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}", result.narrative_text)
    )
    assert strength_hits >= 3, (
        f"narrative must inline strength= for >=3 hops; got {strength_hits}"
    )
    assert period_hits >= 1, (
        f"narrative must inline >=1 ISO date range; got {period_hits}"
    )
    assert not result.degraded
