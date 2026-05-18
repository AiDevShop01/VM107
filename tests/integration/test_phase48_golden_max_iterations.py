"""Phase 48 Plan 08b — E2E golden: MAX_ITERATIONS path. REQ-48-E2E-GOLDEN-MAX-ITER.

Critic returns REFINE on every iteration through the locked MAX_ITERATIONS=3
budget. On the 3rd REFINE (no iterations left), loop terminates with
MAX_ITERATIONS. Targets must NOT repeat across iterations (or convergence
stall fires first) and identity must stay tight (or identity_drift fires first).
"""
from __future__ import annotations

from core.agents.refinement_orchestrator import run_refinement_loop
from core.agents.refinement_orchestrator.policy_constants import MAX_ITERATIONS
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


def test_golden_max_iterations(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    # MAX_ITERATIONS=3 → orchestrator allows iteration indices {0, 1, 2}.
    # On iter 0 the loop sees REFINE → routes once → iter 1 sees REFINE → routes
    # once → iter 2 sees REFINE → no iterations remaining → MAX_ITERATIONS.
    assert MAX_ITERATIONS == 3

    # Three CODE_MODULE targets with DIFFERENT canonical_issue_ids so
    # convergence_detector doesn't fire (it needs the same key tuple set in
    # consecutive iterations).
    issue_ids = [
        CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
        CanonicalIssueId.CONFIRMATION_BARS_INSUFFICIENT,
        CanonicalIssueId.STOP_WIDTH_TOO_TIGHT,
    ]
    verdicts = [
        make_critic_verdict(
            verdict="REFINE",
            refinement_targets=[
                make_refinement_target(
                    canonical_issue_id=iid,
                    issue_type=f"type_{i}",
                    target_field="code",
                )
            ],
        )
        for i, iid in enumerate(issue_ids)
    ]

    # Strategy regenerates per iter (we mark version differently) but spec stays
    # CLOSE to iter 0 (CODE_MODULE targets only — identity_scorer.compute_score
    # only walks StrategySpec fields).
    specs = [
        make_strategy_spec(name="spec_iter0", version="0.0.1"),
    ]
    codes = [
        make_code_module(version="0.0.1"),
        make_code_module(version="0.0.2"),
        make_code_module(version="0.0.3"),
    ]
    builds = [make_build_report() for _ in range(MAX_ITERATIONS)]
    backtests = [make_backtest_result() for _ in range(MAX_ITERATIONS)]

    seen_events: list[dict] = []
    wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        run_strategy_returns=specs,  # only iter 0 calls Strategy (CODE_MODULE-only targets)
        run_code_returns=codes,
        run_build_returns=builds,
        run_backtest_returns=backtests,
        run_critic_returns=verdicts,
        seen_events=seen_events,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == TerminationReason.MAX_ITERATIONS
    assert outcome.rejected_strategy_id is not None
    assert outcome.accepted_strategy_id is None

    emitted = event_types_emitted(seen_events)
    # Expect MAX_ITERATIONS-many iteration_started + critic_verdict_received events.
    assert emitted.count("iteration_started") == MAX_ITERATIONS
    assert emitted.count("critic_verdict_received") == MAX_ITERATIONS

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert len(rejected) == 1
    assert rejected[0]["termination_reason"] == "MAX_ITERATIONS"
