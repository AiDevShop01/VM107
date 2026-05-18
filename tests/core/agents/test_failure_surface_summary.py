"""Phase 48 Plan 48-08a — REQ-48-D12 failure_surface_summary derivation.

CONTEXT § Decision 12: rejected_strategies docs carry a
``failure_surface_summary: {primary_failure_mode, secondary_failure_modes}``.
This dict is the substrate for Phase 49/62 failure-mode learning.

Derivation table:
  HARD_VETO              -> primary="catastrophic_metric", secondary=vetoes_triggered metric names
  IDENTITY_DRIFT         -> primary="identity_drift",     secondary=diff_breakdown fields
  CONVERGENCE_STALL      -> primary="convergence_stall",  secondary=repeated target issue_types
  BUDGET_EXCEEDED_ITERATION -> primary="budget_exhaustion", secondary=["ITERATION"]
  BUDGET_EXCEEDED_LOOP   -> primary="budget_exhaustion",  secondary=["LOOP"]
  MAX_ITERATIONS         -> primary="max_iterations",     secondary=critic_history terminal verdicts
  CRITIC_REJECT          -> primary="no_edge",            secondary=critic failure_modes
  BUILD_FAILURE (+ subs) -> primary="pipeline_failure",   secondary=[degraded_stage]
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import CriticVerdict, RefinementTarget


def test_derive_hard_veto():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    vetoes = [
        {"metric": "max_drawdown", "threshold": 0.35, "actual": 0.42},
        {"metric": "win_rate", "threshold": 0.30, "actual": 0.18},
    ]
    summary = derive_failure_surface_summary(
        termination_reason="HARD_VETO",
        verdict_or_none=None,
        veto_history=vetoes,
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "catastrophic_metric"
    assert set(summary["secondary_failure_modes"]) == {"max_drawdown", "win_rate"}


def test_derive_identity_drift():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    diff = [
        {"field": "strategy_family", "severity": "HIGH", "was": "BREAKOUT", "now": "MEAN_REVERSION"},
        {"field": "timeframes", "severity": "MEDIUM", "was": ["1H"], "now": ["15m"]},
    ]
    summary = derive_failure_surface_summary(
        termination_reason="IDENTITY_DRIFT",
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=diff,
        critic_history=[],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "identity_drift"
    assert set(summary["secondary_failure_modes"]) == {"strategy_family", "timeframes"}


def test_derive_convergence_stall():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    repeated = [
        RefinementTarget(
            scope="STRATEGY_SPEC",
            canonical_issue_id="OVERFIT_SIGNATURE",
            target_field="rules",
            issue="entry filter",
            issue_type="entry_filter_too_loose",
            severity="HIGH",
            suggested_change="adjust",
            source_critic_verdict_id="cv2",
        ),
        RefinementTarget(
            scope="STRATEGY_SPEC",
            canonical_issue_id="EXPECTANCY_UNSTABLE",
            target_field="rules",
            issue="stability",
            issue_type="stability",
            severity="MEDIUM",
            suggested_change="adjust",
            source_critic_verdict_id="cv2",
        ),
    ]
    summary = derive_failure_surface_summary(
        termination_reason="CONVERGENCE_STALL",
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=repeated,
    )
    assert summary["primary_failure_mode"] == "convergence_stall"
    assert set(summary["secondary_failure_modes"]) == {"entry_filter_too_loose", "stability"}


def test_derive_budget_exceeded_iteration():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    summary = derive_failure_surface_summary(
        termination_reason="BUDGET_EXCEEDED_ITERATION",
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "budget_exhaustion"
    assert summary["secondary_failure_modes"] == ["ITERATION"]


def test_derive_budget_exceeded_loop():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    summary = derive_failure_surface_summary(
        termination_reason="BUDGET_EXCEEDED_LOOP",
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "budget_exhaustion"
    assert summary["secondary_failure_modes"] == ["LOOP"]


def test_derive_max_iterations():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    summary = derive_failure_surface_summary(
        termination_reason="MAX_ITERATIONS",
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=["cv0", "cv1", "cv2"],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "max_iterations"
    # secondary_failure_modes is the critic_history list (terminal verdicts).
    assert summary["secondary_failure_modes"] == ["cv0", "cv1", "cv2"]


def test_derive_critic_reject():
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    verdict = CriticVerdict(
        verdict="REJECT",
        confidence=0.5,
        refinement_targets=[],
        failure_modes=["OVERFIT", "REGIME_FRAGILE"],
        rationale="no edge",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id="cv2",
        registry_snapshot_hash="snapshot_test",
        schema_version=1,
    )
    summary = derive_failure_surface_summary(
        termination_reason="CRITIC_REJECT",
        verdict_or_none=verdict,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "no_edge"
    assert set(summary["secondary_failure_modes"]) == {"OVERFIT", "REGIME_FRAGILE"}


@pytest.mark.parametrize(
    "termination_reason,expected_stage",
    [
        ("BUILD_FAILURE", "BUILD_FAILURE"),
        ("CRITIC_DEGRADED", "CRITIC_DEGRADED"),
        ("STRATEGY_DEGRADED", "STRATEGY_DEGRADED"),
        ("CODE_DEGRADED", "CODE_DEGRADED"),
        ("BUILD_FAILED", "BUILD_FAILED"),
        ("BACKTEST_DEGRADED", "BACKTEST_DEGRADED"),
    ],
)
def test_derive_build_failure_family(termination_reason, expected_stage):
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    summary = derive_failure_surface_summary(
        termination_reason=termination_reason,
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=None,
    )
    assert summary["primary_failure_mode"] == "pipeline_failure"
    assert summary["secondary_failure_modes"] == [expected_stage]


def test_derive_unknown_termination_reason_safe_default():
    """Unknown termination_reason falls through to a safe placeholder summary."""
    from core.agents.refinement_orchestrator.rejection_path import (
        derive_failure_surface_summary,
    )

    summary = derive_failure_surface_summary(
        termination_reason="UNKNOWN_FUTURE_STATE",
        verdict_or_none=None,
        veto_history=[],
        identity_diff_breakdown=None,
        critic_history=[],
        repeated_targets=None,
    )
    # Safe default: primary=termination_reason itself, secondary empty.
    assert summary["primary_failure_mode"] == "UNKNOWN_FUTURE_STATE"
    assert summary["secondary_failure_modes"] == []
