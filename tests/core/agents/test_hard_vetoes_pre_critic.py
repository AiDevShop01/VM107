"""Phase 48 Plan 48-04 Task 4.3 — hard vetoes evaluated BEFORE Critic LLM runs.

Implements REQ-48-D9. CONTEXT § Decision 9:
"Universal, domain-agnostic, deterministic Python constants. Executed
BEFORE Critic LLM ever runs."

Two-pronged contract:

1. The pure function `check_hard_vetoes(backtest_result)` correctly identifies
   each of the 4 catastrophic-only veto conditions and returns the triggered
   list (or empty list when nothing trips).

2. The pre-critic call-order invariant: when a backtest would trip a hard
   veto AND a hypothetical Critic verdict would say ACCEPT, the orchestrator
   stops BEFORE invoking run_critic. We simulate the contract by composing
   check_hard_vetoes + a Mock(run_critic) in a tiny inline driver that mirrors
   what Plan 08b's main_loop will do: if vetoes -> terminate; else -> critic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.contracts.schemas import BacktestMetrics, BacktestResult


def _br(
    *,
    win_rate: float = 0.55,
    rr: float = 1.5,
    max_drawdown: float = 0.10,
    profit_factor: float = 1.6,
    consecutive_losses: int = 0,
    regime_coverage: float = 1.0,
    sample_size: int = 250,
    confidence: float = 0.6,
) -> BacktestResult:
    return BacktestResult(
        metrics=BacktestMetrics(
            win_rate=win_rate,
            rr=rr,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            consecutive_losses=consecutive_losses,
            regime_coverage=regime_coverage,
        ),
        sample_size=sample_size,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Direct veto-checker behavior.
# ---------------------------------------------------------------------------


def test_no_vetoes_returns_empty_list_when_all_metrics_safe():
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    assert check_hard_vetoes(_br()) == []


@pytest.mark.parametrize(
    "kwargs,expected_metric,expected_actual",
    [
        # max_drawdown > 0.35 -> veto
        ({"max_drawdown": 0.42}, "max_drawdown", 0.42),
        # win_rate < 0.30 -> veto
        ({"win_rate": 0.20}, "win_rate", 0.20),
        # consecutive_losses > 10 -> veto
        ({"consecutive_losses": 12}, "consecutive_losses", 12),
        # regime_coverage < 0.20 -> veto
        ({"regime_coverage": 0.10}, "regime_coverage", 0.10),
    ],
)
def test_each_of_four_vetoes_fires_independently(kwargs, expected_metric, expected_actual):
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    triggers = check_hard_vetoes(_br(**kwargs))

    assert len(triggers) == 1
    t = triggers[0]
    assert t["metric"] == expected_metric
    assert t["actual"] == expected_actual
    assert "threshold" in t
    assert "op" in t


def test_multiple_vetoes_can_fire_simultaneously():
    """If a backtest trips 3 vetoes, the result list has 3 entries."""
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    triggers = check_hard_vetoes(
        _br(max_drawdown=0.42, win_rate=0.20, consecutive_losses=15)
    )
    metrics_triggered = {t["metric"] for t in triggers}
    assert metrics_triggered == {"max_drawdown", "win_rate", "consecutive_losses"}
    # The 4th metric (regime_coverage) at default 1.0 should NOT have fired.
    assert "regime_coverage" not in metrics_triggered


def test_veto_entry_carries_threshold_and_op_from_policy_constants():
    """Each veto entry round-trips the planner-locked policy threshold + op."""
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes
    from core.agents.refinement_orchestrator.policy_constants import HARD_VETOES

    triggers = check_hard_vetoes(_br(max_drawdown=0.42))

    assert len(triggers) == 1
    t = triggers[0]
    assert t["threshold"] == HARD_VETOES["max_drawdown"]["value"]
    assert t["op"] == HARD_VETOES["max_drawdown"]["op"]


# ---------------------------------------------------------------------------
# PRE-CRITIC call-order invariant.
#
# The contract Plan 08b's main_loop must honor: if hard_vetoes -> terminate
# with HARD_VETO BEFORE invoking run_critic. We simulate the main_loop here
# (Plan 08b is still a NotImplementedError stub).
# ---------------------------------------------------------------------------


def _stub_main_loop_iteration(backtest_result, *, run_critic):
    """Inline mirror of the Plan 08b main_loop iteration contract.

    Two-gate sequence:
      1. acceptance_floor classifier
      2. hard_vetoes check
      3. Critic LLM (ONLY if neither gate terminated)

    Returns (termination_reason_or_none, critic_was_called).
    """
    from core.agents.refinement_orchestrator.acceptance_floor import (
        classify_acceptance,
    )
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes

    # Gate 1: acceptance floor.
    acceptance = classify_acceptance(backtest_result)
    if acceptance.classification.value == "HARD_REJECT":
        return ("HARD_REJECT", False)

    # Gate 2: hard vetoes (catastrophic only — fires regardless of acceptance pass).
    vetoes = check_hard_vetoes(backtest_result)
    if vetoes:
        return ("HARD_VETO", False)

    # Gate 3: Critic LLM (only reached if both deterministic gates pass).
    _ = run_critic(backtest_result)
    return (None, True)


def test_pre_critic_invariant_veto_terminates_before_run_critic():
    """A vetoing backtest stops Plan 08b's loop BEFORE run_critic is invoked,
    even when the (hypothetical) Critic would have ACCEPTed.
    """
    # The backtest passes the 4 acceptance floors but trips max_drawdown veto:
    # win_rate=0.55, profit_factor=1.6, sample_size=250 all pass; max_drawdown=0.42 vetoes.
    vetoing_backtest = _br(max_drawdown=0.42)

    accept_verdict = MagicMock(name="critic_would_accept", verdict="ACCEPT")
    run_critic_mock = MagicMock(name="run_critic", return_value=accept_verdict)

    termination, critic_called = _stub_main_loop_iteration(
        vetoing_backtest, run_critic=run_critic_mock
    )

    assert termination == "HARD_VETO"
    assert critic_called is False
    assert run_critic_mock.call_count == 0, (
        "run_critic must NOT be called when a hard veto trips — CONTEXT § Decision 9"
    )


def test_pre_critic_invariant_clean_backtest_does_reach_critic():
    """Sanity sibling: when no veto AND acceptance passes, Critic IS invoked."""
    clean_backtest = _br()  # all defaults — safe.

    run_critic_mock = MagicMock(name="run_critic", return_value=MagicMock(verdict="ACCEPT"))

    termination, critic_called = _stub_main_loop_iteration(
        clean_backtest, run_critic=run_critic_mock
    )

    assert termination is None
    assert critic_called is True
    assert run_critic_mock.call_count == 1


def test_pre_critic_invariant_hard_reject_also_terminates_before_critic():
    """Acceptance HARD_REJECT path is also pre-critic (CONTEXT § Decision 8)."""
    # sample_size=10 -> 95% breach -> HARD_REJECT on acceptance floor.
    hard_reject_backtest = _br(sample_size=10)

    run_critic_mock = MagicMock(name="run_critic")

    termination, critic_called = _stub_main_loop_iteration(
        hard_reject_backtest, run_critic=run_critic_mock
    )

    assert termination == "HARD_REJECT"
    assert critic_called is False
    assert run_critic_mock.call_count == 0
