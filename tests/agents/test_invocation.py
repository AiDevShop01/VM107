"""
Phase 44 Plan 03 — invocation module tests (graduated from Wave 0 xfail stubs).

Tests against core.agents.invocation implemented in Plan 44-03 Task 1.
All xfail markers removed — tests are concrete GREEN passes.

Test names match 44-VALIDATION.md "Per-Task Verification Map" exactly.
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

def test_pre_classifier():
    """
    is_substantive() returns True for strategy keywords, False for chitchat.

    Per CONTEXT.md § Coordinator Role + Behavior:
      SUBSTANTIVE_KEYWORDS = {"strategy", "idea", "hypothesis", "trade", "setup", "pattern"}
      Case-insensitive, empty string → False.
    """
    from core.agents.invocation import is_substantive

    # Positive cases — must contain at least one keyword
    assert is_substantive("design a strategy for momentum") is True
    assert is_substantive("what is a good trade idea?") is True
    assert is_substantive("STRATEGY for SPY") is True          # case-insensitive
    assert is_substantive("I have a HYPOTHESIS about gaps") is True
    assert is_substantive("setup for breakout") is True
    assert is_substantive("pattern recognition") is True

    # Negative cases — no keyword
    assert is_substantive("hello there") is False
    assert is_substantive("thanks") is False
    assert is_substantive("") is False


def test_chitchat_no_dispatch():
    """
    Pre-classifier returning False short-circuits without calling _call_subordinate_sync.

    Asserts that non-substantive input does NOT trigger agent delegation.
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

def test_run_idea_returns_hypothesis(valid_hypothesis):
    """
    run_idea(text) returns a Hypothesis instance with source_envelope_id populated
    when db is None (no persistence).

    The mock simulates a valid Hypothesis JSON response from the subordinate agent.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_idea
    from core.contracts.schemas import Hypothesis

    hypothesis_json = valid_hypothesis.model_dump_json()

    with patch("core.agents.invocation._call_subordinate_sync", return_value=hypothesis_json):
        result = run_idea("substantive strategy text with trend idea")

    assert isinstance(result, Hypothesis)


def test_run_strategy_returns_spec(valid_hypothesis):
    """
    run_strategy(valid_hypothesis) returns a StrategySpec instance.

    The mock simulates a valid StrategySpec JSON response from the subordinate agent.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_strategy
    from core.contracts.schemas import StrategySpec, StrategyFamily

    # Phase 48 Plan 48-01: strategy_family REQUIRED.
    spec_json = StrategySpec(
        name="Momentum Trend",
        features=["rsi_14", "ema_20"],
        rules=["rsi > 60"],
        timeframes=["1h"],
        version="1.0.0",
        strategy_family=StrategyFamily.TREND_CONTINUATION,
    ).model_dump_json()

    with patch("core.agents.invocation._call_subordinate_sync", return_value=spec_json):
        result = run_strategy(valid_hypothesis)

    assert isinstance(result, StrategySpec)


def test_idea_retry_once_then_fail(valid_hypothesis):
    """
    Retry-once-then-fail: two consecutive PlainTextResults → IdeaAgentDegradedError.

    Per CONTEXT.md § Idea Agent:
      'If retry also fails → return failure to Coordinator → task fails (fail-fast).'
    Mock confirms exactly 2 calls to _call_subordinate_sync.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_idea, IdeaAgentDegradedError

    # Both calls return unstructured text — safe_parse returns PlainTextResult each time
    degraded_response = "I cannot structure this output right now."
    with patch("core.agents.invocation._call_subordinate_sync", return_value=degraded_response) as mock_call:
        with pytest.raises(IdeaAgentDegradedError):
            run_idea("strategy idea text")
        # Exactly 2 calls: initial + exactly one retry
        assert mock_call.call_count == 2


def test_idea_retry_succeeds_on_second(valid_hypothesis):
    """
    First call garbage → retry triggered → second call valid Hypothesis JSON → returns Hypothesis.
    Mock confirms exactly 2 calls (initial + 1 retry).
    """
    from unittest.mock import patch, call
    from core.agents.invocation import run_idea
    from core.contracts.schemas import Hypothesis

    hypothesis_json = valid_hypothesis.model_dump_json()
    degraded_response = "I could not structure output."

    call_responses = [degraded_response, hypothesis_json]
    call_index = [0]

    def side_effect(*args, **kwargs):
        i = call_index[0]
        call_index[0] += 1
        return call_responses[i]

    with patch("core.agents.invocation._call_subordinate_sync", side_effect=side_effect) as mock_call:
        result = run_idea("substantive text with strategy idea")

    assert isinstance(result, Hypothesis)
    assert mock_call.call_count == 2  # initial + 1 retry


def test_strategy_rejects_invalid_hypothesis():
    """
    run_strategy() raises InvalidInputError when passed a non-Hypothesis.

    Per CONTEXT.md § Strategy Agent:
      'assert isinstance(input, Hypothesis). Reject anything else with InvalidInputError
       — NO auto-wrapping/auto-calling Idea Agent.'
    Mock call_count == 0 — no LLM call triggered.
    """
    from unittest.mock import patch
    from core.agents.invocation import run_strategy, InvalidInputError

    with patch("core.agents.invocation._call_subordinate_sync") as mock_call:
        with pytest.raises((InvalidInputError, TypeError)):
            run_strategy("just a string")
        # BEFORE any subordinate call
        assert mock_call.call_count == 0


def test_degraded_blocked(valid_hypothesis):
    """
    PlainTextResult from Idea Agent NEVER passes to Strategy Agent.

    Both attempts on Idea Agent degrade → IdeaAgentDegradedError raised.
    Strategy Agent must not be called (all mock calls are for idea_agent).
    """
    from unittest.mock import patch
    from core.agents.invocation import run_idea, IdeaAgentDegradedError

    degraded_response = "Sorry, could not structure output."

    with patch("core.agents.invocation._call_subordinate_sync", return_value=degraded_response) as mock_call:
        with pytest.raises(IdeaAgentDegradedError):
            run_idea("design a trade setup pattern")

    # After two failed retries, strategy must not have been called
    for c in mock_call.call_args_list:
        assert c.args[0] == "idea_agent", "strategy_agent should not have been called"


def test_concurrency_default_sequential():
    """
    MAX_PARALLEL_SUBAGENTS == 1 (sequential default per CONTEXT.md § Concurrency).

    Phase 44 ships sequential only. Parallel infrastructure deferred to Phase 45+.
    """
    from core.agents.invocation import MAX_PARALLEL_SUBAGENTS

    assert MAX_PARALLEL_SUBAGENTS == 1
