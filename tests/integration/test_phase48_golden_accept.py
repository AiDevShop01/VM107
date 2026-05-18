"""Phase 48 Plan 08b — E2E golden: ACCEPT path. REQ-48-E2E-GOLDEN-ACCEPT.

Constructs a Hypothesis that runs iter 0 cleanly through Strategy/Code/Build/
Backtest, then the Critic returns ACCEPT on the first pass. Asserts:
  * outcome.termination_reason == TerminationReason.ACCEPTED
  * outcome.accepted_strategy_id is not None
  * emit sequence includes refinement_loop_started + iteration_started +
    critic_verdict_received + strategy_accepted + loop_terminated.
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


def test_golden_accept(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    spec = make_strategy_spec()
    code = make_code_module()
    build = make_build_report(status="success")
    backtest = make_backtest_result()  # passes all floors
    verdict = make_critic_verdict(verdict="ACCEPT")

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

    assert outcome.termination_reason == TerminationReason.ACCEPTED
    assert outcome.accepted_strategy_id is not None
    assert outcome.rejected_strategy_id is None
    assert outcome.final_iteration == 0

    emitted = event_types_emitted(seen_events)
    assert "refinement_loop_started" in emitted
    assert "iteration_started" in emitted
    assert "critic_verdict_received" in emitted
    assert "strategy_accepted" in emitted
    assert "loop_terminated" in emitted

    # Mongo trajectory preserved.
    loops = list(mongo_test_db["refinement_loops"].find({}))
    assert len(loops) == 1
    assert loops[0]["termination_reason"] == "ACCEPTED"
    assert loops[0]["iteration_artifact_ids"], "iter-0 bundle must persist"
    assert loops[0]["spec_iter0_id"], "iter-0 anchor must persist"

    accepted = list(mongo_test_db["accepted_strategies"].find({}))
    assert len(accepted) == 1
    assert accepted[0]["accepted_strategy_id"] == outcome.accepted_strategy_id
    assert accepted[0]["_worm_locked"] is True
