"""Phase 86 Plan 07 — macro_historical_analyst agent tests (TDD RED/GREEN).

Tests:
1. test_narrative_contains_sample_size_and_period — happy-path LLM includes N + period; success envelope
2. test_narrative_under_50_words — narrative word count <= 50
3. test_reprompts_once_when_first_emit_missing_n — LLM omits N on first call; re-prompted; second includes N+period; success
4. test_error_envelope_when_both_emits_miss_citations — LLM omits both times; error envelope, confidence='low'
5. test_cot_trail_written_once — write_cot_trail called exactly once per invocation with correct args
6. test_malformed_envelope_raises — missing provenance.sample_size triggers KeyError

Shape reference: fixture matches vm102_event_study envelope from Plan 86-03 /event-study
endpoint contract (N=25, period 1990-2025, 3 asset curves).
TODO: re-verify fixture against live 86-03 endpoint once Plan 86-03 deploys to dev.
"""
from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.phase_86

from agents.macro_historical_analyst.agent import MacroHistoricalAnalyst

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "event_study_envelope_sample.json"


@pytest.fixture
def fixture_envelope():
    return json.loads(FIXTURE.read_text())


def test_narrative_contains_sample_size_and_period(fixture_envelope):
    """Agent returns success envelope; narrative cites N=25 and period=1990-2025."""
    narrative = "The 25 CPI beats above 0.3% since 1990-2025 saw Gold average -1.2% over 5 days; USD +0.6%."
    with patch("agents.macro_historical_analyst.agent.call_llm", return_value=narrative):
        with patch("agents.macro_historical_analyst.agent.write_cot_trail"):
            agent = MacroHistoricalAnalyst()
            out = agent.invoke(
                envelope=fixture_envelope["envelope"],
                indicator_name=fixture_envelope["indicator_name"],
                asset_names=fixture_envelope["asset_names"],
                result=fixture_envelope["result"],
            )
    assert out["error"] is None
    assert "25" in out["result"]["narrative"]
    assert "1990-2025" in out["result"]["narrative"]
    assert out["envelope"]["confidence"] == "high"


def test_narrative_under_50_words(fixture_envelope):
    """Agent narrative must be 50 words or fewer."""
    narrative = "The 25 CPI beats above 0.3% since 1990-2025 saw Gold average -1.2% over 5 days; USD +0.6%."
    with patch("agents.macro_historical_analyst.agent.call_llm", return_value=narrative):
        with patch("agents.macro_historical_analyst.agent.write_cot_trail"):
            agent = MacroHistoricalAnalyst()
            out = agent.invoke(
                envelope=fixture_envelope["envelope"],
                indicator_name=fixture_envelope["indicator_name"],
                asset_names=fixture_envelope["asset_names"],
                result=fixture_envelope["result"],
            )
    assert len(out["result"]["narrative"].split()) <= 50


def test_reprompts_once_when_first_emit_missing_n(fixture_envelope):
    """When first LLM emit omits N, agent re-prompts once; second emit includes both; success returned."""
    call_log = []

    def fake_llm(prompt):
        call_log.append(prompt)
        if len(call_log) == 1:
            return "Gold declined post-release in the period 1990-2025."  # missing N=25
        return "Across 25 events since 1990-2025, Gold declined post-release."  # includes both

    with patch("agents.macro_historical_analyst.agent.call_llm", side_effect=fake_llm):
        with patch("agents.macro_historical_analyst.agent.write_cot_trail"):
            agent = MacroHistoricalAnalyst()
            out = agent.invoke(
                envelope=fixture_envelope["envelope"],
                indicator_name=fixture_envelope["indicator_name"],
                asset_names=fixture_envelope["asset_names"],
                result=fixture_envelope["result"],
            )

    assert len(call_log) == 2  # re-prompted exactly once
    assert out["error"] is None
    assert "25" in out["result"]["narrative"]
    assert "1990-2025" in out["result"]["narrative"]


def test_error_envelope_when_both_emits_miss_citations(fixture_envelope):
    """When LLM omits N+period on both attempts, returns error envelope with confidence='low'."""
    with patch("agents.macro_historical_analyst.agent.call_llm",
               return_value="Generic statement without numbers."):
        with patch("agents.macro_historical_analyst.agent.write_cot_trail"):
            agent = MacroHistoricalAnalyst()
            out = agent.invoke(
                envelope=fixture_envelope["envelope"],
                indicator_name=fixture_envelope["indicator_name"],
                asset_names=fixture_envelope["asset_names"],
                result=fixture_envelope["result"],
            )
    assert out["envelope"]["confidence"] == "low"
    assert out["error"] is not None
    assert out["error"]["code"] == "MissingCitations"
    assert set(out["error"]["meta"]["missing"]) <= {"sample_size", "period"}
    assert out["result"] is None


def test_cot_trail_written_once(fixture_envelope):
    """write_cot_trail called exactly once per invocation with agent_id and terminated_at."""
    cot_mock = MagicMock()
    with patch("agents.macro_historical_analyst.agent.call_llm",
               return_value="The 25 events since 1990-2025 saw Gold decline."):
        with patch("agents.macro_historical_analyst.agent.write_cot_trail", cot_mock):
            agent = MacroHistoricalAnalyst()
            agent.invoke(
                envelope=fixture_envelope["envelope"],
                indicator_name=fixture_envelope["indicator_name"],
                asset_names=fixture_envelope["asset_names"],
                result=fixture_envelope["result"],
            )
    assert cot_mock.call_count == 1
    # write_cot_trail(agent_id, invocation_id, cot_events, terminated_at=...)
    args, kwargs = cot_mock.call_args
    assert args[0] == "macro_historical_analyst"
    assert "terminated_at" in kwargs


def test_malformed_envelope_raises(fixture_envelope):
    """Envelope missing provenance.sample_size raises KeyError."""
    bad_envelope = {"provenance": {}}  # missing sample_size and period
    with patch("agents.macro_historical_analyst.agent.write_cot_trail"):
        agent = MacroHistoricalAnalyst()
        with pytest.raises(KeyError):
            agent.invoke(
                envelope=bad_envelope,
                indicator_name=fixture_envelope["indicator_name"],
                asset_names=fixture_envelope["asset_names"],
                result=fixture_envelope["result"],
            )
