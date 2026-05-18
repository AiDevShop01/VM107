"""Phase 48 Plan 08b — E2E golden: IDENTITY_DRIFT. REQ-48-E2E-GOLDEN-IDENTITY-DRIFT.

Iter 0 builds spec with strategy_family=BREAKOUT.
Iter 1 (after REFINE) mutates strategy_family=MEAN_REVERSION (IMMUTABLE_CORE
field, weight=0.5 → identity score drops to 0.5 < 0.70 threshold for iter 1).
Identity gate fires AFTER Critic verdict on iter 1.

Critically asserts: every compute_score call is anchored to spec_iter0
(NEVER spec_prev_iter) via call_args spy.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import core.agents.refinement_orchestrator.identity_scorer as _identity_scorer
from core.agents.refinement_orchestrator import run_refinement_loop
from core.contracts.schemas import StrategyFamily, TerminationReason

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


def test_golden_identity_drift_anchors_to_iter_0(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    spec_iter0 = make_strategy_spec(
        name="spec_iter0", family=StrategyFamily.BREAKOUT, version="0.0.1"
    )
    # Iter 1 mutates strategy_family (IMMUTABLE_CORE) → identity_score drops.
    spec_iter1 = make_strategy_spec(
        name="spec_iter0",  # name kept stable
        family=StrategyFamily.MEAN_REVERSION,  # IMMUTABLE_CORE change
        version="0.0.2",
    )

    # Iter 0 REFINE with STRATEGY_SPEC-scoped target so routing calls run_strategy
    # again on iter 1.
    target = make_refinement_target(
        scope="STRATEGY_SPEC", target_field="features", issue_type="refine_features"
    )
    verdict_iter0 = make_critic_verdict(
        verdict="REFINE", refinement_targets=[target]
    )
    verdict_iter1 = make_critic_verdict(
        verdict="REFINE",
        refinement_targets=[make_refinement_target(scope="CODE_MODULE")],
    )

    # Wrap compute_score with a spy that records every call's spec_iter0 arg.
    real_compute_score = _identity_scorer.compute_score
    captured_args = []

    def _spy_compute_score(spec_new, spec_iter0_arg):
        captured_args.append((spec_new, spec_iter0_arg))
        return real_compute_score(spec_new, spec_iter0_arg)

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.compute_score",
        _spy_compute_score,
    )

    seen_events: list[dict] = []
    wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        run_strategy_returns=[spec_iter0, spec_iter1],  # called twice (STRATEGY_SPEC scope)
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

    assert outcome.termination_reason == TerminationReason.IDENTITY_DRIFT
    assert outcome.rejected_strategy_id is not None
    assert outcome.accepted_strategy_id is None

    # Spy assertion — every captured spec_iter0 arg MUST be the iter-0 spec.
    # We compare by family (a stable IMMUTABLE_CORE field unique to iter 0).
    assert len(captured_args) >= 1, "compute_score should have been called at least once"
    for spec_new, spec_iter0_arg in captured_args:
        assert spec_iter0_arg.strategy_family == StrategyFamily.BREAKOUT, (
            "Identity gate MUST anchor to spec_iter0 (CONTEXT § Decision 10). "
            f"Got family={spec_iter0_arg.strategy_family} for spec_iter0 arg."
        )

    emitted = event_types_emitted(seen_events)
    assert "identity_drift_detected" in emitted
    assert "strategy_rejected" in emitted

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert rejected[0]["termination_reason"] == "IDENTITY_DRIFT"
