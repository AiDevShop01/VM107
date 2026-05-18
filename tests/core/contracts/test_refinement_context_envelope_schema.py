"""Phase 48 Plan 48-01 — REQ-48-D5. RefinementContextEnvelope 9-field schema."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import (
    CanonicalIssueId,
    RefinementContextEnvelope,
    RefinementTarget,
)


def _target() -> RefinementTarget:
    return RefinementTarget(
        scope="STRATEGY_SPEC",
        canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR,
        target_field="features",
        issue="too low",
        issue_type="STATISTICAL",
        severity="MEDIUM",
        suggested_change="add filter",
        source_critic_verdict_id="cv_001",
    )


def test_refinement_context_envelope_round_trip() -> None:
    """9 fields round-trip."""
    env = RefinementContextEnvelope(
        iteration=2,
        prior_strategy_spec_id="ss_001",
        prior_code_module_id="cm_001",
        prior_build_report_id="br_001",
        prior_backtest_result_id="bt_001",
        critic_verdict_id="cv_001",
        refinement_targets=[_target()],
        identity_score=0.85,
        registry_snapshot_hash="hash_abc",
    )
    rehydrated = RefinementContextEnvelope.model_validate(env.model_dump())
    assert rehydrated.iteration == 2
    assert rehydrated.prior_strategy_spec_id == "ss_001"
    assert rehydrated.prior_code_module_id == "cm_001"
    assert rehydrated.prior_build_report_id == "br_001"
    assert rehydrated.prior_backtest_result_id == "bt_001"
    assert rehydrated.critic_verdict_id == "cv_001"
    assert len(rehydrated.refinement_targets) == 1
    assert rehydrated.identity_score == pytest.approx(0.85)
    assert rehydrated.registry_snapshot_hash == "hash_abc"


def test_refinement_context_envelope_rejects_extra_field() -> None:
    """extra='forbid' on BaseContract."""
    with pytest.raises(ValidationError):
        RefinementContextEnvelope(
            iteration=1,
            prior_strategy_spec_id="ss",
            prior_code_module_id="cm",
            prior_build_report_id="br",
            prior_backtest_result_id="bt",
            critic_verdict_id="cv",
            refinement_targets=[],
            identity_score=0.9,
            registry_snapshot_hash="h",
            extra_unknown_field="boom",  # type: ignore[call-arg]
        )


def test_refinement_context_envelope_identity_score_in_zero_one() -> None:
    """identity_score must be in [0.0, 1.0]."""
    with pytest.raises(ValidationError):
        RefinementContextEnvelope(
            iteration=1,
            prior_strategy_spec_id="ss",
            prior_code_module_id="cm",
            prior_build_report_id="br",
            prior_backtest_result_id="bt",
            critic_verdict_id="cv",
            refinement_targets=[],
            identity_score=1.5,
            registry_snapshot_hash="h",
        )
