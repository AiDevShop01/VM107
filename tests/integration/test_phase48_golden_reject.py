"""Phase 48 Plan 08b — E2E golden: CRITIC_REJECT path. REQ-48-E2E-GOLDEN-REJECT.

Critic returns verdict=REJECT on iter 0. Asserts:
  * outcome.termination_reason == TerminationReason.CRITIC_REJECT
  * outcome.rejected_strategy_id is not None (no accepted_strategy_id)
  * emit sequence includes strategy_rejected + loop_terminated (NO strategy_accepted)
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


def test_golden_reject(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    spec = make_strategy_spec()
    code = make_code_module()
    build = make_build_report(status="success")
    backtest = make_backtest_result()  # passes floors so we reach Critic
    verdict = make_critic_verdict(verdict="REJECT")

    seen_events: list[dict] = []
    wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        run_strategy_returns=[spec],
        run_code_returns=[code],
        run_build_returns=[build],
        run_backtest_returns=[backtest],
        run_critic_returns=[verdict],
        seen_events=seen_events,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == TerminationReason.CRITIC_REJECT
    assert outcome.rejected_strategy_id is not None
    assert outcome.accepted_strategy_id is None

    emitted = event_types_emitted(seen_events)
    assert "strategy_rejected" in emitted
    assert "loop_terminated" in emitted
    assert "strategy_accepted" not in emitted

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert len(rejected) == 1
    assert rejected[0]["termination_reason"] == "CRITIC_REJECT"
    assert rejected[0]["_worm_locked"] is True
    # NO accepted_strategies doc.
    accepted = list(mongo_test_db["accepted_strategies"].find({}))
    assert len(accepted) == 0
