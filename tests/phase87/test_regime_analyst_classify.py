"""Phase 87 Plan 06 (Wave 3) — agent classify-step unit tests.

Exercises the agent's anchor-direction → classifier → BeliefStore (stub)
→ transition_probability pipeline using all-mock collaborators. No
network, no DB.

Companion to test_regime_analyst_on_release.py (which exercises the full
60s end-to-end path) and test_regime_classifier_rules.py (which tests
the classifier table in isolation).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from agents.macro_regime_analyst.agent import MacroRegimeAnalyst
from agents.macro_regime_analyst.skill_regime_narration import (
    RegimeNarrationSkill,
)

pytestmark = pytest.mark.phase_87


def _make_agent(
    *,
    directions: tuple[int, int, int],
    prior_regime: str | None = "expansion",
    analogues: list | None = None,
    llm_text: str = "The stagflation regime persists [ref:release:abc123].",
    belief_confidence: float = 0.5,
):
    """Build a MacroRegimeAnalyst wired to MagicMock collaborators."""
    provider = MagicMock()
    provider.directions_at.return_value = directions

    analogue_client = MagicMock()
    analogue_client.find_analogues.return_value = analogues or []

    beliefs = MagicMock()
    beliefs.query.return_value = {
        "probability": 0.5,
        "confidence": belief_confidence,
    }

    llm = MagicMock()
    llm.complete.return_value = llm_text

    envelope_repo = MagicMock()
    envelope_repo.persist.return_value = uuid.uuid4()
    b1_repo = MagicMock()
    b1_repo.persist.return_value = uuid.uuid4()

    persist = MagicMock()
    persist.last_regime.return_value = prior_regime
    persist.create.return_value = uuid.uuid4()

    ws = MagicMock()

    agent = MacroRegimeAnalyst(
        anchor_direction_provider=provider,
        analogue_client=analogue_client,
        belief_store_client=beliefs,
        narration_skill=RegimeNarrationSkill(llm_router=llm),
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )
    return agent, {
        "provider": provider,
        "analogue_client": analogue_client,
        "beliefs": beliefs,
        "llm": llm,
        "envelope_repo": envelope_repo,
        "b1_repo": b1_repo,
        "persist": persist,
        "ws": ws,
    }


class TestRegimeAnalystClassifyStep:
    """Direct unit tests of the classify-then-persist pipeline."""

    def test_stagflation_hard_flip_emits_transition_probability_1(
        self, release_event_factory
    ):
        agent, mocks = _make_agent(
            directions=(+1, +1, -1),
            prior_regime="expansion",
        )
        result = agent.run(release_event_factory())

        assert result.current_regime == "stagflation"
        assert result.prior_regime == "expansion"
        assert result.transition_probability == 1.0, (
            "hard flip from expansion→stagflation must emit "
            "transition_probability == 1.0 in Wave 3"
        )
        mocks["persist"].create.assert_called_once()
        mocks["ws"].publish.assert_called_once()
        # WS topic name follows macro.regime.<indicator_id>.updated contract.
        topic = mocks["ws"].publish.call_args[0][0]
        assert topic.startswith("macro.regime.")
        assert topic.endswith(".updated")

    def test_carry_prior_emits_same_regime_and_probability_zero(
        self, release_event_factory
    ):
        # (0, 0, 0) → carry_prior per LOCK-10
        agent, mocks = _make_agent(
            directions=(0, 0, 0),
            prior_regime="inflation",
            llm_text="The inflation regime persists; comparable to [ref:release:p1].",
        )
        result = agent.run(release_event_factory())

        assert result.current_regime == "inflation"
        assert result.prior_regime == "inflation"
        assert result.transition_probability == 0.0, (
            "carry_prior must emit transition_probability == 0.0"
        )
        mocks["persist"].create.assert_called_once()

    def test_cold_start_falls_back_to_expansion(self, release_event_factory):
        """No prior persisted regime → default to LOCK-2 baseline 'expansion'."""
        agent, mocks = _make_agent(
            directions=(0, 0, +1),  # expansion
            prior_regime=None,      # cold start
            llm_text="The expansion regime continues [ref:release:cold].",
        )
        result = agent.run(release_event_factory())
        assert result.prior_regime == "expansion"
        assert result.current_regime == "expansion"

    def test_belief_store_stub_called_with_subject_type_regime(
        self, release_event_factory
    ):
        """Wave 3 contract — BeliefStore.query is called; signature is stable
        across Wave 3 (stub) and Wave 5 (real B9) so Plan 87-09 swaps the
        client without touching the agent's call site."""
        agent, mocks = _make_agent(directions=(+1, +1, -1))
        agent.run(release_event_factory())
        mocks["beliefs"].query.assert_called_once()
        kwargs = mocks["beliefs"].query.call_args[1]
        assert kwargs.get("subject_type") == "regime"
        # subject_id is the classified regime
        assert kwargs.get("subject_id") == "stagflation"

    def test_analogue_client_called_with_release_surprise(
        self, release_event_factory
    ):
        """Analogue client receives the current release's surprise + indicator."""
        agent, mocks = _make_agent(directions=(+1, +1, -1))
        event = release_event_factory(surprise=0.45)
        agent.run(event)
        mocks["analogue_client"].find_analogues.assert_called_once()
        kwargs = mocks["analogue_client"].find_analogues.call_args[1]
        assert kwargs["indicator_id"] == event["indicator_id"]
        assert kwargs["surprise"] == 0.45

    def test_empty_analogues_marks_envelope_degraded(self, release_event_factory):
        """Phase 86 outage → envelope is degraded even when classifier OK."""
        agent, mocks = _make_agent(
            directions=(+1, +1, -1),
            analogues=[],  # Phase 86 returned nothing
        )
        result = agent.run(release_event_factory())
        assert result.degraded is True, (
            "empty analogue list must mark envelope degraded — Phase 86 "
            "layer was missing and downstream consumers need to know"
        )

    def test_supporting_evidence_includes_three_anchor_citations(
        self, release_event_factory
    ):
        """Anchor section must list CPI + UNRATE + GDP with their directions."""
        agent, mocks = _make_agent(directions=(+1, +1, -1))
        result = agent.run(release_event_factory())
        anchors = [
            s for s in result.supporting_evidence if s.get("kind") == "anchor"
        ]
        assert len(anchors) == 3
        anchor_ids = {a["indicator_id"] for a in anchors}
        assert anchor_ids == {"CPIAUCSL", "UNRATE", "GDP"}
        anchor_directions = {a["indicator_id"]: a["direction"] for a in anchors}
        assert anchor_directions == {"CPIAUCSL": 1, "UNRATE": 1, "GDP": -1}
