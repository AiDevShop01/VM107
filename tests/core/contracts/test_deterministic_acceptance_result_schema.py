"""Phase 48 Plan 48-01 — REQ-48-D8. DeterministicAcceptanceResult schema."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import (
    AcceptanceClassification,
    DeterministicAcceptanceResult,
)


def test_acceptance_classification_three_values() -> None:
    """REQ-48-D8: HARD_REJECT, REFINABLE_WEAKNESS, CRITIC_ELIGIBLE."""
    members = {m.name for m in AcceptanceClassification}
    assert members == {"HARD_REJECT", "REFINABLE_WEAKNESS", "CRITIC_ELIGIBLE"}


def test_deterministic_acceptance_result_round_trip() -> None:
    """Round-trip with passed=True / CRITIC_ELIGIBLE."""
    r = DeterministicAcceptanceResult(
        passed=True,
        failed_constraints=[],
        metrics_snapshot={"win_rate": 0.55, "max_drawdown": 0.15},
        classification=AcceptanceClassification.CRITIC_ELIGIBLE,
    )
    rehydrated = DeterministicAcceptanceResult.model_validate(r.model_dump())
    assert rehydrated.passed is True
    assert rehydrated.failed_constraints == []
    assert rehydrated.metrics_snapshot["win_rate"] == pytest.approx(0.55)
    assert rehydrated.classification == AcceptanceClassification.CRITIC_ELIGIBLE


def test_deterministic_acceptance_result_failure_path() -> None:
    """passed=False with failed_constraints and HARD_REJECT classification."""
    r = DeterministicAcceptanceResult(
        passed=False,
        failed_constraints=["sample_size", "max_drawdown"],
        metrics_snapshot={"sample_size": 50, "max_drawdown": 0.42},
        classification=AcceptanceClassification.HARD_REJECT,
    )
    assert r.passed is False
    assert "sample_size" in r.failed_constraints
    assert r.classification == AcceptanceClassification.HARD_REJECT


def test_deterministic_acceptance_result_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        DeterministicAcceptanceResult(
            passed=True,
            failed_constraints=[],
            metrics_snapshot={},
            classification=AcceptanceClassification.CRITIC_ELIGIBLE,
            unknown="boom",  # type: ignore[call-arg]
        )
