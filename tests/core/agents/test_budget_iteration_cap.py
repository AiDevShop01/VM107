"""Phase 48 Plan 48-05 Task 5.3 — budget governor iteration cap.

REQ-48-D14. CONTEXT § Decision 14:
  "Per-iteration cap protects single refinement cycle from local runaway."

BudgetGovernor.check_iteration_cap() raises LoopBudgetExceeded(scope=ITERATION)
when iteration consumed_usd > BUDGET_CAPS_USD['per_iteration'] (1.50).

Two-track accounting: LLM cognition USD + INFRASTRUCTURE wall-time USD are
SUMMED for cap comparison but tracked separately for telemetry. Wall-time
cap is checked alongside USD cap.
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


def _state(budget_snapshot: dict | None = None) -> RefinementLoopState:
    """Helper: minimal RefinementLoopState."""
    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop_t_001",
        root_hypothesis_id="hyp_001",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash-abc",
        iteration=1,
        max_iterations=3,
        strategy_version="0.1.0",
        code_version="0.1.0",
        budget_snapshot=budget_snapshot or {},
        started_at=now,
        updated_at=now,
    )


def _llm_cost(usd: float, tokens_in: int = 100, tokens_out: int = 50, wall_ms: int = 1000) -> ExecutionCost:
    return ExecutionCost(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usd_cost=usd,
        wall_time_ms=wall_ms,
        category="LLM",
    )


def _infra_cost(usd: float = 0.0, wall_ms: int = 60_000) -> ExecutionCost:
    return ExecutionCost(
        tokens_in=0,
        tokens_out=0,
        usd_cost=usd,
        wall_time_ms=wall_ms,
        category="INFRASTRUCTURE",
    )


def test_check_iteration_cap_under_limit_returns_none():
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(_llm_cost(usd=0.50))
    g.track_cost(_infra_cost(usd=0.20))

    # Sum 0.70 < 1.50 cap.
    result = g.check_iteration_cap()
    assert result is None


def test_check_iteration_cap_over_limit_raises_iteration_scope():
    """0.80 (LLM) + 0.80 (INFRASTRUCTURE) = 1.60 > 1.50 cap -> raises."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(_llm_cost(usd=0.80))
    g.track_cost(_infra_cost(usd=0.80))

    with pytest.raises(LoopBudgetExceeded) as exc_info:
        g.check_iteration_cap()

    err = exc_info.value
    assert err.scope == "ITERATION"
    assert err.consumed_usd > BUDGET_CAPS_USD["per_iteration"]
    assert err.cap_usd == BUDGET_CAPS_USD["per_iteration"]


def test_check_iteration_cap_exact_limit_does_not_raise():
    """Exactly at cap (1.50) is NOT over."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(_llm_cost(usd=BUDGET_CAPS_USD["per_iteration"]))

    assert g.check_iteration_cap() is None


def test_check_iteration_cap_wall_time_over_limit_raises_iteration_scope():
    """Wall-time also enforced at iteration scope."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    # 1 minute over the per-iteration wall-time cap.
    over_ms = BUDGET_CAPS_WALL_TIME_MS["per_iteration"] + 60_000
    g.track_cost(_infra_cost(usd=0.10, wall_ms=over_ms))

    with pytest.raises(LoopBudgetExceeded) as exc_info:
        g.check_iteration_cap()
    assert exc_info.value.scope == "ITERATION"


def test_reset_iteration_tally_zeros_iteration_but_preserves_loop():
    """After reset, iteration counters are zeroed; loop counters preserved."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(_llm_cost(usd=0.40))
    g.track_cost(_infra_cost(usd=0.20))
    # Iteration consumed 0.60 (under cap).
    snap_before = g.budget_snapshot
    assert snap_before["iteration_usd"] == pytest.approx(0.60)
    assert snap_before["loop_total_usd"] == pytest.approx(0.60)

    g.reset_iteration_tally()
    snap_after = g.budget_snapshot
    assert snap_after["iteration_usd"] == pytest.approx(0.0)
    # Loop totals MUST be preserved.
    assert snap_after["loop_total_usd"] == pytest.approx(0.60)


def test_track_cost_rejects_unknown_category():
    """ExecutionCost only allows LLM | INFRASTRUCTURE; defensive guard."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor
    # ExecutionCost Pydantic Literal already validates this at construction.
    # This test confirms the Pydantic guard fires.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionCost(
            tokens_in=0, tokens_out=0, usd_cost=0.1, wall_time_ms=100,
            category="OTHER",  # type: ignore[arg-type]
        )
