"""Phase 48 Plan 08b — E2E golden: HARD_VETO path. REQ-48-E2E-GOLDEN-VETO.

Backtest trips max_drawdown > 0.35 (catastrophic veto, § Decision 9).
Asserts:
  * outcome.termination_reason == TerminationReason.HARD_VETO
  * run_critic was NEVER called (vetoes pre-empt Critic; CONTEXT § Anti-Patterns)
  * emit sequence includes hard_veto_triggered + strategy_rejected + loop_terminated
"""
from __future__ import annotations

from core.agents.refinement_orchestrator import run_refinement_loop
from core.contracts.schemas import TerminationReason

from tests.integration._phase48_golden_helpers import (
    event_types_emitted,
    make_backtest_result,
    make_build_report,
    make_code_module,
    make_critic_verdict,
    make_strategy_spec,
    wire_orchestrator_for_golden,
)


def test_golden_hard_veto_max_drawdown(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    # Catastrophic drawdown trips hard veto BEFORE Critic.
    backtest = make_backtest_result(max_drawdown=0.50, sample_size=400)
    spec = make_strategy_spec()
    code = make_code_module()

    seen_events: list[dict] = []
    mocks = wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        run_strategy_returns=[spec],
        run_code_returns=[code],
        run_build_returns=[make_build_report()],
        run_backtest_returns=[backtest],
        run_critic_returns=[make_critic_verdict()],  # never called
        seen_events=seen_events,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == TerminationReason.HARD_VETO
    assert outcome.rejected_strategy_id is not None
    assert outcome.accepted_strategy_id is None

    # Critical: Critic must NEVER run when veto trips.
    assert mocks["run_critic"].call_count == 0

    emitted = event_types_emitted(seen_events)
    assert "hard_veto_triggered" in emitted
    assert "strategy_rejected" in emitted
    assert "loop_terminated" in emitted
    assert "critic_verdict_received" not in emitted

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert len(rejected) == 1
    assert rejected[0]["termination_reason"] == "HARD_VETO"
    assert rejected[0]["veto_history"], "veto_history must be populated"
