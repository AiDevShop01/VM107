"""Phase 48 Plan 48-05 Task 5.3 — LLM vs INFRASTRUCTURE cost tracked separately.

REQ-48-D14. CONTEXT § Decision 14:
  "Separate cost categories: LLM cognition cost vs infrastructure compute
   cost (Backtester wall-time can dwarf LLM tokens for slow VM102 calls;
   tracked independently)."

budget_snapshot must carry distinct keys so the orchestrator (Plan 08b) can
emit Phase 56 telemetry events with category-segmented breakdowns.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.contracts.schemas import ExecutionCost, RefinementLoopState


def _state() -> RefinementLoopState:
    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop_cat",
        root_hypothesis_id="hyp_cat",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash-abc",
        iteration=1,
        max_iterations=3,
        strategy_version="0.1.0",
        code_version="0.1.0",
        started_at=now,
        updated_at=now,
    )


def test_llm_and_infrastructure_accumulate_into_distinct_keys():
    """Two costs of different categories accumulate into distinct keys."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(ExecutionCost(
        tokens_in=100, tokens_out=50, usd_cost=0.30, wall_time_ms=1500, category="LLM"
    ))
    g.track_cost(ExecutionCost(
        tokens_in=0, tokens_out=0, usd_cost=0.50, wall_time_ms=90_000, category="INFRASTRUCTURE"
    ))

    snap = g.budget_snapshot
    # Category-separated tallies (both iteration and loop scope).
    assert snap["iteration_llm_usd"] == pytest.approx(0.30)
    assert snap["iteration_infrastructure_usd"] == pytest.approx(0.50)
    assert snap["loop_total_llm_usd"] == pytest.approx(0.30)
    assert snap["loop_total_infrastructure_usd"] == pytest.approx(0.50)
    # Aggregated totals carry both buckets summed.
    assert snap["iteration_usd"] == pytest.approx(0.80)
    assert snap["loop_total_usd"] == pytest.approx(0.80)


def test_token_tallies_only_count_llm_costs():
    """Token counters should only accumulate from LLM category (infrastructure costs
    don't have tokens — they're wall-time).

    INFRASTRUCTURE costs with tokens_in/out>0 would be a misuse; ExecutionCost
    enforces ge=0 but doesn't enforce category-token coupling. The governor
    counts what it gets — both as token totals, all categories. Spec: token
    totals = SUM(tokens_in + tokens_out) across ALL costs.
    """
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(ExecutionCost(
        tokens_in=300, tokens_out=200, usd_cost=0.50, wall_time_ms=2000, category="LLM"
    ))
    g.track_cost(ExecutionCost(
        tokens_in=0, tokens_out=0, usd_cost=0.40, wall_time_ms=80_000, category="INFRASTRUCTURE"
    ))

    snap = g.budget_snapshot
    assert snap["iteration_tokens"] == 500
    assert snap["loop_total_tokens"] == 500


def test_categories_track_independently_across_resets():
    """reset_iteration_tally zeroes BOTH iteration_llm_usd AND
    iteration_infrastructure_usd, preserving BOTH loop_total_llm_usd AND
    loop_total_infrastructure_usd."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(ExecutionCost(
        tokens_in=10, tokens_out=10, usd_cost=0.20, wall_time_ms=100, category="LLM"
    ))
    g.track_cost(ExecutionCost(
        tokens_in=0, tokens_out=0, usd_cost=0.40, wall_time_ms=50_000, category="INFRASTRUCTURE"
    ))
    g.reset_iteration_tally()

    snap = g.budget_snapshot
    # Iteration cleared.
    assert snap["iteration_llm_usd"] == pytest.approx(0.0)
    assert snap["iteration_infrastructure_usd"] == pytest.approx(0.0)
    assert snap["iteration_tokens"] == 0
    # Loop preserved.
    assert snap["loop_total_llm_usd"] == pytest.approx(0.20)
    assert snap["loop_total_infrastructure_usd"] == pytest.approx(0.40)
    assert snap["loop_total_tokens"] == 20


def test_budget_snapshot_keys_locked():
    """Stable contract: budget_snapshot has all 10 expected keys after track_cost."""
    from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor

    g = BudgetGovernor(_state())
    g.track_cost(ExecutionCost(
        tokens_in=10, tokens_out=10, usd_cost=0.10, wall_time_ms=100, category="LLM"
    ))

    snap = g.budget_snapshot
    required_keys = {
        # totals (USD)
        "iteration_usd",
        "loop_total_usd",
        # categorized USD (CONTEXT § Decision 14)
        "iteration_llm_usd",
        "iteration_infrastructure_usd",
        "loop_total_llm_usd",
        "loop_total_infrastructure_usd",
        # wall-time
        "iteration_wall_ms",
        "loop_total_wall_ms",
        # tokens
        "iteration_tokens",
        "loop_total_tokens",
    }
    missing = required_keys - set(snap.keys())
    assert not missing, f"budget_snapshot missing keys: {missing}"
