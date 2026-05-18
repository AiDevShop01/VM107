"""Phase 48 Plan 08b — E2E golden: CONVERGENCE_STALL. REQ-48-E2E-GOLDEN-CONVERGENCE.

Critic emits the SAME (scope, canonical_issue_id, issue_type) tuple on
iteration 1 as on iteration 0. detect_convergence_stall fires AFTER iter 1's
Critic verdict, BEFORE iteration 2 would start.
"""
from __future__ import annotations

from core.agents.refinement_orchestrator import run_refinement_loop
from core.contracts.schemas import CanonicalIssueId, TerminationReason

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


def test_golden_convergence_stall(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    # Iter 0 emits target T; iter 1 emits the SAME (scope, issue_id, issue_type) → stall.
    target_seed = make_refinement_target(
        canonical_issue_id=CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
        issue_type="sample_too_small",
        target_field="code",
        scope="CODE_MODULE",
    )
    same_target = make_refinement_target(
        canonical_issue_id=CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
        issue_type="sample_too_small",
        target_field="code",  # target_field doesn't affect convergence key
        scope="CODE_MODULE",
    )

    verdict_iter0 = make_critic_verdict(
        verdict="REFINE", refinement_targets=[target_seed]
    )
    verdict_iter1 = make_critic_verdict(
        verdict="REFINE", refinement_targets=[same_target]
    )

    seen_events: list[dict] = []
    wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        run_strategy_returns=[make_strategy_spec()],
        run_code_returns=[
            make_code_module(version="0.0.1"),
            make_code_module(version="0.0.2"),
        ],
        run_build_returns=[make_build_report(), make_build_report()],
        run_backtest_returns=[make_backtest_result(), make_backtest_result()],
        run_critic_returns=[verdict_iter0, verdict_iter1],
        seen_events=seen_events,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == TerminationReason.CONVERGENCE_STALL
    assert outcome.rejected_strategy_id is not None
    assert outcome.accepted_strategy_id is None

    emitted = event_types_emitted(seen_events)
    assert "convergence_stall_detected" in emitted
    assert "strategy_rejected" in emitted
    assert "loop_terminated" in emitted

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert len(rejected) == 1
    assert rejected[0]["termination_reason"] == "CONVERGENCE_STALL"
