"""Phase 48 Plan 48-05 Task 5.3 — budget preflight (no grace iteration).

REQ-48-D14. CONTEXT § Decision 14:
  "Preflight check BEFORE iteration start: remaining_loop_budget <
   estimated_iteration_floor -> terminate immediately (no grace iteration)."

Also CONTEXT § Anti-Patterns: "Final grace iteration on budget exhaustion"
is explicitly REJECTED (caps become soft suggestions).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.agents.refinement_orchestrator.policy_constants import BUDGET_CAPS_USD
from core.contracts.schemas import ExecutionCost, RefinementLoopState


def _state(loop_total_usd: float = 0.0) -> RefinementLoopState:
    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop_pref",
        root_hypothesis_id="hyp_pref",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash-abc",
        iteration=2,
        max_iterations=3,
        strategy_version="0.1.0",
        code_version="0.1.0",
        budget_snapshot={"loop_total_usd": loop_total_usd},
        started_at=now,
        updated_at=now,
    )


def _llm(usd: float) -> ExecutionCost:
    return ExecutionCost(tokens_in=10, tokens_out=10, usd_cost=usd, wall_time_ms=100, category="LLM")


def test_preflight_returns_true_when_remaining_above_floor():
    """remaining = 5.00 - 0 = 5.00. Floor = 1.50 -> remaining > floor -> True."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    assert g.preflight(estimated_iteration_floor_usd=1.50) is True


def test_preflight_returns_false_when_remaining_below_floor():
    """Spent 4.70; remaining = 5.00 - 4.70 = 0.30; floor = 1.50 -> False."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(_llm(usd=4.70))
    # Don't reset iteration -- preflight should still see loop_total_usd
    # because it consults loop level.
    assert g.preflight(estimated_iteration_floor_usd=1.50) is False


def test_preflight_no_grace_iteration_anti_pattern():
    """If remaining loop budget < floor -> False -- ORCHESTRATOR MUST TERMINATE
    without running one final iteration. This is CONTEXT § Anti-Patterns:
    'Final grace iteration on budget exhaustion' is REJECTED."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    # Remaining = 5.00 - 4.99 = 0.01. Floor = 1.50.
    g = BudgetGovernor(_state(loop_total_usd=4.99))
    assert g.preflight(estimated_iteration_floor_usd=1.50) is False
    # And remaining must be the small leftover.
    remaining = BUDGET_CAPS_USD["per_loop"] - 4.99
    assert remaining == pytest.approx(0.01)


def test_preflight_exact_match_returns_true():
    """remaining == floor -> True (we have JUST enough)."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state(loop_total_usd=BUDGET_CAPS_USD["per_loop"] - 1.50))
    assert g.preflight(estimated_iteration_floor_usd=1.50) is True


def test_preflight_uses_loop_remaining_not_iteration_remaining():
    """Preflight is a LOOP-level check (CONTEXT § Decision 14)."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    # Loop has spent 4.50, iteration has spent 0 (reset before preflight).
    # Remaining_loop = 5.00 - 4.50 = 0.50. Floor 1.50 -> False.
    g = BudgetGovernor(_state(loop_total_usd=4.50))
    assert g.preflight(estimated_iteration_floor_usd=1.50) is False
