"""Phase 48 Plan 08b — E2E golden: BUILD_FAILURE family. REQ-48-E2E-GOLDEN-BUILD-FAILURE.

Parametrized over the 5 sub-states (CONTEXT § Decision 4 + planner discretion):
  STRATEGY_DEGRADED, CODE_DEGRADED, BUILD_FAILED, BACKTEST_DEGRADED, CRITIC_DEGRADED.

For each: configures a typed wrapper to raise its DegradedError, asserts the
matching termination_reason on outcome.
"""
from __future__ import annotations

import pytest

from core.agents.invocation import (
    BacktesterDegradedError,
    CodeAgentDegradedError,
    CriticDegradedError,
    StrategyAgentDegradedError,
)
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


def _err(cls):
    return cls(error_chain=["attempt_1_degraded", "attempt_2_degraded"])


@pytest.mark.parametrize(
    "degraded_stage,expected_reason,wrapper_kwarg",
    [
        ("strategy", TerminationReason.STRATEGY_DEGRADED, "run_strategy_returns"),
        ("code", TerminationReason.CODE_DEGRADED, "run_code_returns"),
        ("backtest", TerminationReason.BACKTEST_DEGRADED, "run_backtest_returns"),
        ("critic", TerminationReason.CRITIC_DEGRADED, "run_critic_returns"),
        # BUILD_FAILED is deterministic — BuildReport(status="failure") rather
        # than a degraded-LLM exception. Covered by a separate test below.
    ],
)
def test_golden_build_failure_sub_states(
    degraded_stage,
    expected_reason,
    wrapper_kwarg,
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    err_cls = {
        "strategy": StrategyAgentDegradedError,
        "code": CodeAgentDegradedError,
        "backtest": BacktesterDegradedError,
        "critic": CriticDegradedError,
    }[degraded_stage]

    # Defaults — only the parametrized stage degrades.
    wrapper_args = {
        "run_strategy_returns": [make_strategy_spec()],
        "run_code_returns": [make_code_module()],
        "run_build_returns": [make_build_report()],
        "run_backtest_returns": [make_backtest_result()],
        "run_critic_returns": [make_critic_verdict(verdict="ACCEPT")],
    }
    wrapper_args[wrapper_kwarg] = [_err(err_cls)]

    seen_events: list[dict] = []
    wire_orchestrator_for_golden(
        monkeypatch,
        db=mongo_test_db,
        snapshot_hash=frozen_registry_snapshot_hash,
        seen_events=seen_events,
        **wrapper_args,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == expected_reason
    assert outcome.rejected_strategy_id is not None
    assert outcome.accepted_strategy_id is None

    emitted = event_types_emitted(seen_events)
    assert "strategy_rejected" in emitted
    assert "loop_terminated" in emitted

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert len(rejected) == 1
    assert rejected[0]["termination_reason"] == expected_reason.value


def test_golden_build_failed_via_build_report_failure(
    valid_hypothesis_id,
    mongo_test_db,
    frozen_registry_snapshot_hash,
    monkeypatch,
):
    """BUILD_FAILED on iter 1 via BuildReport(status='failure') after REFINE."""
    from tests.integration._phase48_golden_helpers import make_refinement_target

    verdict_iter0 = make_critic_verdict(
        verdict="REFINE",
        refinement_targets=[make_refinement_target(scope="CODE_MODULE")],
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
        run_build_returns=[
            make_build_report(status="success"),
            make_build_report(status="failure"),  # iter 1 build fails
        ],
        run_backtest_returns=[make_backtest_result()],
        run_critic_returns=[verdict_iter0],
        seen_events=seen_events,
    )

    outcome = run_refinement_loop(valid_hypothesis_id)

    assert outcome.termination_reason == TerminationReason.BUILD_FAILED

    rejected = list(mongo_test_db["rejected_strategies"].find({}))
    assert rejected[0]["termination_reason"] == "BUILD_FAILED"
