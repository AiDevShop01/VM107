"""Phase 48 Plan 48-01 — REQ-48-D1. CriticVerdict 9-field schema + verdict literal."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import (
    CanonicalIssueId,
    CriticVerdict,
    RefinementTarget,
)


def _valid_target() -> RefinementTarget:
    return RefinementTarget(
        scope="STRATEGY_SPEC",
        canonical_issue_id=CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
        target_field="features",
        issue="sample size insufficient",
        issue_type="STATISTICAL",
        severity="HIGH",
        suggested_change="increase backtest window",
        source_critic_verdict_id="cv_parent_001",
    )


def test_critic_verdict_round_trip_preserves_all_fields() -> None:
    """REQ-48-D1: 9 fields round-trip through model_validate + model_dump."""
    target = _valid_target()
    verdict = CriticVerdict(
        verdict="REFINE",
        confidence=0.72,
        refinement_targets=[target],
        failure_modes=["sample_size_too_small"],
        rationale="The backtest window covers too few trades.",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id=None,
        registry_snapshot_hash="phase48-test-snapshot-deadbeef",
    )
    dumped = verdict.model_dump()
    rehydrated = CriticVerdict.model_validate(dumped)
    assert rehydrated.verdict == "REFINE"
    assert rehydrated.confidence == pytest.approx(0.72)
    assert len(rehydrated.refinement_targets) == 1
    assert rehydrated.failure_modes == ["sample_size_too_small"]
    assert rehydrated.rationale.startswith("The backtest")
    assert rehydrated.loaded_skills == ["breakout_critic"]
    assert rehydrated.source_critic_verdict_id is None
    assert rehydrated.registry_snapshot_hash == "phase48-test-snapshot-deadbeef"
    assert rehydrated.schema_version == 1


def test_critic_verdict_accepts_three_verdict_literals() -> None:
    """verdict ∈ {ACCEPT, REFINE, REJECT} only."""
    for v in ("ACCEPT", "REFINE", "REJECT"):
        verdict = CriticVerdict(
            verdict=v,  # type: ignore[arg-type]
            confidence=0.5,
            refinement_targets=[],
            failure_modes=[],
            rationale="ok",
            loaded_skills=[],
            source_critic_verdict_id=None,
            registry_snapshot_hash="h",
        )
        assert verdict.verdict == v


def test_critic_verdict_rejects_unknown_verdict() -> None:
    """Anything outside the 3 literal values raises ValidationError."""
    with pytest.raises(ValidationError):
        CriticVerdict(
            verdict="MAYBE",  # type: ignore[arg-type]
            confidence=0.5,
            refinement_targets=[],
            failure_modes=[],
            rationale="bad",
            loaded_skills=[],
            source_critic_verdict_id=None,
            registry_snapshot_hash="h",
        )


def test_critic_verdict_confidence_clamp_high() -> None:
    """confidence > 1.0 raises ValidationError (clamp via ge/le)."""
    with pytest.raises(ValidationError):
        CriticVerdict(
            verdict="ACCEPT",
            confidence=1.5,
            refinement_targets=[],
            failure_modes=[],
            rationale="ok",
            loaded_skills=[],
            source_critic_verdict_id=None,
            registry_snapshot_hash="h",
        )


def test_critic_verdict_confidence_clamp_low() -> None:
    """confidence < 0.0 raises ValidationError."""
    with pytest.raises(ValidationError):
        CriticVerdict(
            verdict="REJECT",
            confidence=-0.01,
            refinement_targets=[],
            failure_modes=[],
            rationale="ok",
            loaded_skills=[],
            source_critic_verdict_id=None,
            registry_snapshot_hash="h",
        )
