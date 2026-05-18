"""Phase 48 Plan 48-05 Task 5.3 — budget governor loop-aggregate cap.

REQ-48-D14. CONTEXT § Decision 14:
  "Per-loop total cap protects global refinement search from aggregate
   runaway."

BUDGET_CAPS_USD['per_loop'] = 5.00; BUDGET_CAPS_WALL_TIME_MS['per_loop'] = 60min.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.agents.refinement_orchestrator.policy_constants import (
    BUDGET_CAPS_USD,
    BUDGET_CAPS_WALL_TIME_MS,
)
from core.contracts.exceptions import LoopBudgetExceeded
from core.contracts.schemas import ExecutionCost, RefinementLoopState


def _state() -> RefinementLoopState:
    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop_t_002",
        root_hypothesis_id="hyp_002",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash-abc",
        iteration=1,
        max_iterations=3,
        strategy_version="0.1.0",
        code_version="0.1.0",
        budget_snapshot={},
        started_at=now,
        updated_at=now,
    )


def _llm(usd: float, wall_ms: int = 1000) -> ExecutionCost:
    return ExecutionCost(
        tokens_in=10, tokens_out=10, usd_cost=usd, wall_time_ms=wall_ms, category="LLM"
    )


def test_check_loop_cap_under_limit_returns_none():
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    # Three iterations of 1.40 each.
    for _ in range(3):
        g.track_cost(_llm(usd=1.40))
        g.reset_iteration_tally()
    # loop_total = 4.20 < 5.00 cap.
    assert g.check_loop_cap() is None
    assert g.budget_snapshot["loop_total_usd"] == pytest.approx(4.20)


def test_check_loop_cap_over_limit_raises_loop_scope():
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    # 3 iterations of 1.40 = 4.20, then 4th adds 1.00 -> 5.20 > 5.00 cap.
    for _ in range(3):
        g.track_cost(_llm(usd=1.40))
        g.reset_iteration_tally()
    g.track_cost(_llm(usd=1.00))

    with pytest.raises(LoopBudgetExceeded) as exc_info:
        g.check_loop_cap()

    err = exc_info.value
    assert err.scope == "LOOP"
    assert err.consumed_usd > BUDGET_CAPS_USD["per_loop"]
    assert err.cap_usd == BUDGET_CAPS_USD["per_loop"]


def test_check_loop_cap_wall_time_over_limit_raises_loop_scope():
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    # One mega-cost over the per-loop wall-time cap (60 min).
    over_ms = BUDGET_CAPS_WALL_TIME_MS["per_loop"] + 60_000
    g.track_cost(_llm(usd=0.10, wall_ms=over_ms))

    with pytest.raises(LoopBudgetExceeded) as exc_info:
        g.check_loop_cap()
    assert exc_info.value.scope == "LOOP"


def test_loop_total_accumulates_across_resets():
    """reset_iteration_tally must preserve loop_total_usd and loop_total_wall_ms."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(_llm(usd=1.00, wall_ms=2000))
    g.reset_iteration_tally()
    g.track_cost(_llm(usd=0.80, wall_ms=1500))
    g.reset_iteration_tally()
    g.track_cost(_llm(usd=0.50, wall_ms=500))

    snap = g.budget_snapshot
    assert snap["loop_total_usd"] == pytest.approx(2.30)
    assert snap["loop_total_wall_ms"] == 4000
    # Last iteration still has 0.50.
    assert snap["iteration_usd"] == pytest.approx(0.50)
    assert snap["iteration_wall_ms"] == 500


def test_budget_snapshot_round_trips_through_state():
    """Governor accepts an existing budget_snapshot dict from RefinementLoopState
    so a checkpointed loop can resume."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    now = datetime.now(timezone.utc)
    pre_snap = {
        "loop_total_usd": 2.50,
        "loop_total_wall_ms": 30_000,
        "loop_total_llm_usd": 1.20,
        "loop_total_infrastructure_usd": 1.30,
        "iteration_usd": 0.0,
        "iteration_wall_ms": 0,
        "iteration_llm_usd": 0.0,
        "iteration_infrastructure_usd": 0.0,
        "loop_total_tokens": 500,
        "iteration_tokens": 0,
    }
    state = RefinementLoopState(
        loop_id="loop_resume",
        root_hypothesis_id="hyp_resume",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash-abc",
        iteration=2,
        max_iterations=3,
        strategy_version="0.1.0",
        code_version="0.1.0",
        budget_snapshot=pre_snap,
        started_at=now,
        updated_at=now,
    )
    g = BudgetGovernor(state)
    assert g.budget_snapshot["loop_total_usd"] == pytest.approx(2.50)
    assert g.budget_snapshot["loop_total_wall_ms"] == 30_000
