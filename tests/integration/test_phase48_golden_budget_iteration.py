"""Phase 48 Plan 08b — E2E golden: BUDGET_EXCEEDED_ITERATION. REQ-48-E2E-GOLDEN-BUDGET-ITER.

Forces governor.check_iteration_cap() to raise LoopBudgetExceeded(scope=ITERATION)
by pre-stamping the budget_snapshot with iteration_usd > per_iteration cap.
"""
from __future__ import annotations

from core.agents.refinement_orchestrator import run_refinement_loop
from core.agents.refinement_orchestrator.policy_constants import BUDGET_CAPS_USD
from core.contracts.schemas import TerminationReason

from tests.integration._phase48_golden_helpers import (
    event_types_emitted,
    make_backtest_result,
    make_build_report,
    make_code_module,
    make_critic_verdict,
    make_refinement_target,
    make_strategy_spec,
    wire_orchestrator_for_golden,
)


def test_golden_budget_exceeded_iteration(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    # Critic emits REFINE so we reach the post-Critic iteration cap check.
    verdict_iter0 = make_critic_verdict(
        verdict="REFINE",
        refinement_targets=[make_refinement_target(scope="CODE_MODULE")],
    )

    # Pre-arm budget snapshot via a budget_governor.BudgetGovernor monkey:
    # We patch the BudgetGovernor class so its __init__ sets iteration_usd
    # OVER the per-iteration cap.
    from core.agents.refinement_orchestrator import main_loop as _ml

    original_governor = _ml.BudgetGovernor

    class _OvercappedGovernor(original_governor):
        def __init__(self, state):
            super().__init__(state)
            # Force iteration_usd over the cap so check_iteration_cap fires.
            self._budget_snapshot["iteration_usd"] = (
                BUDGET_CAPS_USD["per_iteration"] + 1.0
            )

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.BudgetGovernor",
        _OvercappedGovernor,
    )

    seen_events: list[dict] = []
    wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        run_strategy_returns=[make_strategy_spec()],
        run_code_returns=[make_code_module()],
        run_build_returns=[make_build_report()],
        run_backtest_returns=[make_backtest_result()],
        run_critic_returns=[verdict_iter0],
        seen_events=seen_events,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == TerminationReason.BUDGET_EXCEEDED_ITERATION
    emitted = event_types_emitted(seen_events)
    # budget_exceeded emitted with scope=ITERATION
    budget_events = [e for e in seen_events if e["event_type"] == "budget_exceeded"]
    assert budget_events, "budget_exceeded must be emitted"
    assert budget_events[-1]["payload"]["scope"] == "ITERATION"
    assert "strategy_rejected" in emitted
    assert "loop_terminated" in emitted

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert rejected[0]["termination_reason"] == "BUDGET_EXCEEDED_ITERATION"
