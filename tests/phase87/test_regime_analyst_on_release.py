"""Phase 87 Plan 06 (Wave 3) — end-to-end on-release acceptance test.

REQ-87-3 acceptance: synthetic release event triggers the agent and the
envelope persists within 60s naming one of 7 LOCK-2 regimes with >=1
historical analogue citation + >=3 anchor indicator citations.

Companion to VALIDATION row 87-03-02. The test uses all-mock
collaborators (no Phase 86 HTTP, no DB) so the timing measures the
agent's own work, not external service availability — REQ-87-3 says
the agent's contribution must fit inside the 60s budget; external
service latency is measured separately by Plan 87-14 Wave 8 UAT.
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock

import pytest

from agents.macro_regime_analyst.agent import MacroRegimeAnalyst
from agents.macro_regime_analyst.historical_analogue_client import (
    HistoricalAnalogue,
)
from agents.macro_regime_analyst.skill_regime_narration import (
    RegimeNarrationSkill,
)

pytestmark = pytest.mark.phase_87


_LOCK_2_REGIMES = {
    "expansion",
    "slowdown",
    "inflation",
    "disinflation",
    "stagflation",
    "recession",
    "recovery",
}


def _build_agent_with_three_analogues(prior_regime: str = "expansion"):
    """Wire an agent against mocks returning 3 analogues + a passing LLM."""
    provider = MagicMock()
    provider.directions_at.return_value = (+1, +1, -1)  # stagflation flip

    analogues = [
        HistoricalAnalogue(
            release_id="rel-1",
            release_date="2022-03-10",
            indicator_id="CPIAUCSL",
            surprise=0.3,
            sample_size=180,
            evidence_period="2020-01-01/2025-01-01",
        ),
        HistoricalAnalogue(
            release_id="rel-2",
            release_date="2022-04-12",
            indicator_id="CPIAUCSL",
            surprise=0.2,
            sample_size=180,
            evidence_period="2020-01-01/2025-01-01",
        ),
        HistoricalAnalogue(
            release_id="rel-3",
            release_date="2022-05-11",
            indicator_id="CPIAUCSL",
            surprise=0.4,
            sample_size=180,
            evidence_period="2020-01-01/2025-01-01",
        ),
    ]
    analogue_client = MagicMock()
    analogue_client.find_analogues.return_value = analogues

    beliefs = MagicMock()
    beliefs.query.return_value = {"probability": 0.5, "confidence": 0.6}

    llm = MagicMock()
    llm.complete.return_value = (
        "Current stagflation regime with high transition probability; "
        "[ref:release:rel-1] [ref:release:rel-2] [ref:release:rel-3]."
    )

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
        "envelope_repo": envelope_repo,
        "b1_repo": b1_repo,
        "persist": persist,
        "ws": ws,
        "analogues": analogues,
    }


class TestRegimeAnalystOnRelease:
    """REQ-87-3 end-to-end acceptance + VALIDATION row 87-03-02."""

    def test_envelope_persists_within_60s_naming_one_of_seven_regimes(
        self, release_event_factory
    ):
        agent, _ = _build_agent_with_three_analogues()

        t0 = time.monotonic()
        result = agent.run(release_event_factory())
        elapsed = time.monotonic() - t0

        assert elapsed < 60.0, (
            f"REQ-87-3 60s budget exceeded: {elapsed:.3f}s"
        )
        assert result.current_regime in _LOCK_2_REGIMES, (
            f"envelope must name one of 7 LOCK-2 regimes; "
            f"got {result.current_regime!r}"
        )

    def test_supporting_evidence_has_at_least_one_analogue_citation(
        self, release_event_factory
    ):
        agent, _ = _build_agent_with_three_analogues()
        result = agent.run(release_event_factory())

        analogues = [
            s for s in result.supporting_evidence
            if s.get("kind") == "analogue"
        ]
        assert len(analogues) >= 1, (
            "REQ-87-3: supporting_evidence must include >=1 historical "
            "analogue citation; got 0"
        )

    def test_supporting_evidence_has_at_least_three_anchor_citations(
        self, release_event_factory
    ):
        agent, _ = _build_agent_with_three_analogues()
        result = agent.run(release_event_factory())

        anchors = [
            s for s in result.supporting_evidence
            if s.get("kind") == "anchor"
        ]
        assert len(anchors) >= 3, (
            "REQ-87-3: supporting_evidence must include >=3 anchor "
            f"indicator citations; got {len(anchors)}"
        )
        anchor_indicator_ids = {a["indicator_id"] for a in anchors}
        assert {"CPIAUCSL", "UNRATE", "GDP"} <= anchor_indicator_ids

    def test_persist_repo_create_called_with_full_envelope(
        self, release_event_factory
    ):
        """All envelope fields are written — regression check against
        partial-payload bugs in future refactors."""
        agent, mocks = _build_agent_with_three_analogues()
        agent.run(release_event_factory())

        mocks["persist"].create.assert_called_once()
        kwargs = mocks["persist"].create.call_args[1]
        for required in (
            "event_id", "indicator_id", "current_regime", "prior_regime",
            "transition_probability", "confidence", "supporting_evidence",
            "envelope_id", "b1_artifact_id", "degraded", "generated_at",
        ):
            assert required in kwargs, (
                f"persist_repo.create missing required arg {required!r}; "
                f"got kwargs={sorted(kwargs.keys())}"
            )

    def test_envelope_id_and_b1_id_persisted_together(self, release_event_factory):
        """envelope_repo + b1_repo both called exactly once."""
        agent, mocks = _build_agent_with_three_analogues()
        agent.run(release_event_factory())

        mocks["envelope_repo"].persist.assert_called_once()
        mocks["b1_repo"].persist.assert_called_once()

    def test_ws_topic_publish_thin_invalidation_no_payload(
        self, release_event_factory
    ):
        """WS topic ``macro.regime.<id>.updated`` publishes with payload=None
        per the thin-invalidation contract (matches Plan 87-04 transmission)."""
        agent, mocks = _build_agent_with_three_analogues()
        event = release_event_factory()
        agent.run(event)

        mocks["ws"].publish.assert_called_once()
        topic = mocks["ws"].publish.call_args[0][0]
        kwargs = mocks["ws"].publish.call_args[1]
        assert topic == f"macro.regime.{event['indicator_id']}.updated"
        assert kwargs.get("payload") is None, (
            "WS publish must be thin-invalidation (payload=None); "
            f"got {kwargs}"
        )
