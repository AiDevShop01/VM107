"""Phase 48 Plan 48-01 — REQ-48-D7. CriticVerdict REJECTS is_stalling field (anti-pattern guard).

CONTEXT.md § Decision 7 + § Anti-Patterns:
  Critic NEVER emits is_stalling=true. Convergence detection is orchestration policy,
  not strategic cognition. extra="forbid" on BaseContract enforces this at the schema layer.
"""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import CriticVerdict


def test_critic_verdict_rejects_is_stalling_field() -> None:
    """Constructing with is_stalling=True must raise ValidationError (extra='forbid')."""
    with pytest.raises(ValidationError):
        CriticVerdict(
            verdict="REFINE",
            confidence=0.5,
            refinement_targets=[],
            failure_modes=[],
            rationale="...",
            loaded_skills=[],
            source_critic_verdict_id=None,
            registry_snapshot_hash="h",
            is_stalling=True,  # type: ignore[call-arg]  # anti-pattern field — must be rejected
        )


def test_critic_verdict_rejects_is_stalling_via_model_validate() -> None:
    """Even via dict + model_validate the field is rejected."""
    payload = {
        "verdict": "REFINE",
        "confidence": 0.5,
        "refinement_targets": [],
        "failure_modes": [],
        "rationale": "...",
        "loaded_skills": [],
        "source_critic_verdict_id": None,
        "registry_snapshot_hash": "h",
        "is_stalling": False,
    }
    with pytest.raises(ValidationError):
        CriticVerdict.model_validate(payload)
