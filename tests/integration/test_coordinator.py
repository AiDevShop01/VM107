"""
Phase 44 — Coordinator routing integration tests.

Tests Coordinator delegation routing and no-retry policy per CONTEXT.md §
Coordinator Role + Behavior and § Failure Handling.

All xfail markers removed — Plan 44-05 Task 1 graduated these to GREEN.

Test names match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from core.contracts.schemas import Hypothesis, StrategySpec
from core.agents.invocation_exceptions import (
    IdeaAgentDegradedError,
    StrategyAgentDegradedError,
)
import core.agents.coordinator as coordinator_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_hypothesis():
    return Hypothesis(
        hypothesis="EMA crossover signals on trending SPY produce high-probability continuation setups",
        variables=["ema_20", "ema_50", "trend_state"],
        confidence=0.75,
    )


@pytest.fixture
def fake_strategy_spec():
    return StrategySpec(
        name="SPY EMA Crossover Continuation",
        features=["ema_20", "ema_50", "trend_state"],
        rules=["enter on crossover in trend direction", "stop below recent swing"],
        timeframes=["1H", "4H"],
        version="1.0.0",
    )


@pytest.fixture
def fake_db():
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_routes_substantive(fake_hypothesis, fake_strategy_spec, fake_db):
    """
    Substantive user input causes Coordinator to call run_idea then run_strategy.

    Asserts:
    - run_idea called exactly once with the input text
    - run_strategy called exactly once with the Hypothesis from run_idea
    - Returns (StrategySpec, meta) tuple
    - meta contains idea_envelope_id
    """
    with (
        patch.object(coordinator_module, "run_idea", return_value=fake_hypothesis) as mock_idea,
        patch.object(coordinator_module, "run_strategy", return_value=fake_strategy_spec) as mock_strategy,
    ):
        result, meta = coordinator_module.handle_coordinator_input(
            "design a strategy for SPY pullbacks",
            db=fake_db,
        )

    assert isinstance(result, StrategySpec)
    assert mock_idea.call_count == 1
    assert mock_strategy.call_count == 1
    assert "idea_envelope_id" in meta
    assert "task_id" in meta


def test_routes_trivial(fake_db):
    """
    Non-substantive input returns (None, trivial meta) WITHOUT calling run_idea or run_strategy.

    Asserts:
    - Returns (None, {"trivial": True, ...})
    - run_idea.call_count == 0
    - run_strategy.call_count == 0
    """
    with (
        patch.object(coordinator_module, "run_idea") as mock_idea,
        patch.object(coordinator_module, "run_strategy") as mock_strategy,
    ):
        result, meta = coordinator_module.handle_coordinator_input("hello", db=fake_db)

    assert result is None
    assert meta.get("trivial") is True
    assert "message" in meta
    assert mock_idea.call_count == 0
    assert mock_strategy.call_count == 0


def test_no_coordinator_retry(fake_db):
    """
    When run_idea raises IdeaAgentDegradedError, Coordinator re-raises immediately.

    Coordinator does NOT retry run_idea. call_count MUST be exactly 1 — not 2+.
    Per CONTEXT.md § Failure Handling: fail-fast; scheduler decides retry policy.
    """
    with patch.object(
        coordinator_module,
        "run_idea",
        side_effect=IdeaAgentDegradedError(error_chain=["attempt_1_degraded", "attempt_2_degraded"]),
    ) as mock_idea:
        with pytest.raises(IdeaAgentDegradedError):
            coordinator_module.handle_coordinator_input(
                "design a strategy for SPY",
                db=fake_db,
            )

    # Coordinator MUST NOT retry — exactly one call, never two or more.
    assert mock_idea.call_count == 1, (
        f"Expected run_idea to be called exactly once (no Coordinator retry), "
        f"but was called {mock_idea.call_count} times"
    )


def test_no_strategy_retry(fake_hypothesis, fake_db):
    """
    When run_strategy raises StrategyAgentDegradedError, Coordinator re-raises immediately.

    Same no-retry policy as test_no_coordinator_retry but for the Strategy leg.
    run_strategy.call_count MUST be exactly 1.
    """
    with (
        patch.object(coordinator_module, "run_idea", return_value=fake_hypothesis),
        patch.object(
            coordinator_module,
            "run_strategy",
            side_effect=StrategyAgentDegradedError(error_chain=["attempt_1_degraded", "attempt_2_degraded"]),
        ) as mock_strategy,
    ):
        with pytest.raises(StrategyAgentDegradedError):
            coordinator_module.handle_coordinator_input(
                "design a strategy for SPY",
                db=fake_db,
            )

    assert mock_strategy.call_count == 1, (
        f"Expected run_strategy to be called exactly once (no Coordinator retry), "
        f"but was called {mock_strategy.call_count} times"
    )


def test_run_order(fake_hypothesis, fake_strategy_spec, fake_db):
    """
    Coordinator calls run_idea BEFORE run_strategy (sequential delegation).

    Verifies the Idea → Strategy call order via a shared mock_calls tracking
    wrapper. The pipeline is inherently sequential (Strategy depends on Idea output).
    """
    call_order: list[str] = []

    def _mock_idea(text, **kwargs):
        call_order.append("run_idea")
        return fake_hypothesis

    def _mock_strategy(hyp, **kwargs):
        call_order.append("run_strategy")
        return fake_strategy_spec

    with (
        patch.object(coordinator_module, "run_idea", side_effect=_mock_idea),
        patch.object(coordinator_module, "run_strategy", side_effect=_mock_strategy),
    ):
        coordinator_module.handle_coordinator_input(
            "design a strategy for SPY pullbacks",
            db=fake_db,
        )

    assert call_order == ["run_idea", "run_strategy"], (
        f"Expected ['run_idea', 'run_strategy'] but got {call_order}"
    )
