"""
Phase 44 Wave 0 — invocation module test scaffolds.

Tests against core.agents.invocation (created in Plan 44-03 Task 1).
All tests are xfail(strict=False) until that plan implements the module.

Test names MUST match 44-VALIDATION.md "Per-Task Verification Map" exactly so
downstream plans' <automated> verify commands resolve.

Pre-classifier tests (is_substantive) will graduate to concrete passes in
Plan 44-03 when core.agents.invocation is written.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


# ---------------------------------------------------------------------------
# Pre-classifier tests
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_pre_classifier():
    """
    is_substantive() returns True for strategy keywords, False for chitchat.

    Graduates in Plan 44-03 Task 1 when core.agents.invocation is created.
    """
    from core.agents.invocation import is_substantive

    assert is_substantive("design a strategy for momentum") is True
    assert is_substantive("hello there") is False
    assert is_substantive("what is a good trade idea?") is True
    assert is_substantive("thanks") is False


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_chitchat_no_dispatch():
    """
    Pre-classifier returning False short-circuits without call_subordinate.

    Asserts that non-substantive input does NOT trigger agent delegation.
    Graduates in Plan 44-03 Task 1.
    """
    from unittest.mock import patch
    from core.agents.invocation import is_substantive, route_coordinator_input

    with patch("core.agents.invocation._call_subordinate_sync") as mock_call:
        result = route_coordinator_input("hello there", agent=None)
        mock_call.assert_not_called()
        assert result is None  # signal: Coordinator handles directly


# ---------------------------------------------------------------------------
# Typed wrapper tests
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_run_idea_returns_hypothesis(valid_hypothesis):
    """
    run_idea(text) returns a Hypothesis instance.

    Graduates in Plan 44-03 Task 1 when typed wrappers are implemented.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_idea
    from core.contracts.schemas import Hypothesis

    hypothesis_json = valid_hypothesis.model_dump_json()

    with patch("core.agents.invocation._call_subordinate_sync", return_value=hypothesis_json):
        result = run_idea("substantive strategy text with trend idea")

    assert isinstance(result, Hypothesis)


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_run_strategy_returns_spec(valid_hypothesis):
    """
    run_strategy(valid_hypothesis) returns a StrategySpec instance.

    Graduates in Plan 44-03 Task 1.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_strategy
    from core.contracts.schemas import StrategySpec

    spec_json = StrategySpec(
        name="Momentum Trend",
        features=["rsi_14", "ema_20"],
        rules=["rsi > 60"],
        timeframes=["1h"],
        version="1.0.0",
    ).model_dump_json()

    with patch("core.agents.invocation._call_subordinate_sync", return_value=spec_json):
        result = run_strategy(valid_hypothesis)

    assert isinstance(result, StrategySpec)


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_idea_retry_once_then_fail(valid_hypothesis):
    """
    Retry-once on degraded result behavior for Idea Agent:
    - Two consecutive PlainTextResults → raises IdeaAgentDegradedError
    - First degraded then valid → returns Hypothesis after one retry

    Graduates in Plan 44-03 Task 1.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_idea, IdeaAgentDegradedError
    from core.agents.structured_output import PlainTextResult

    # Both calls return plain text → raises
    degraded_response = "I cannot structure this output right now."
    with patch("core.agents.invocation._call_subordinate_sync", return_value=degraded_response):
        with pytest.raises(IdeaAgentDegradedError):
            run_idea("strategy idea text")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_strategy_rejects_invalid_hypothesis():
    """
    run_strategy() raises TypeError or InvalidInputError when passed a non-Hypothesis.

    Graduates in Plan 44-03 Task 1.
    """
    from core.agents.invocation import run_strategy

    with pytest.raises((TypeError, Exception)):
        run_strategy("not a hypothesis")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_degraded_blocked(valid_hypothesis):
    """
    PlainTextResult from Idea Agent NEVER passes to Strategy Agent.

    Asserts the call chain raises before strategy invocation on degraded.
    Graduates in Plan 44-03 Task 1.
    """
    from unittest.mock import patch, call
    from core.agents.invocation import run_idea, IdeaAgentDegradedError

    degraded_response = "Sorry, could not structure output."

    with patch("core.agents.invocation._call_subordinate_sync", return_value=degraded_response) as mock_call:
        with pytest.raises(IdeaAgentDegradedError):
            run_idea("design a trade setup pattern")

    # After two failed retries, strategy must not have been called
    for c in mock_call.call_args_list:
        assert c.args[0] == "idea_agent", "strategy_agent should not have been called"


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_concurrency_default_sequential():
    """
    MAX_PARALLEL_SUBAGENTS == 1 (sequential default per CONTEXT.md).

    Graduates in Plan 44-03 Task 1 when the constant is defined.
    """
    from core.agents.invocation import MAX_PARALLEL_SUBAGENTS

    assert MAX_PARALLEL_SUBAGENTS == 1
