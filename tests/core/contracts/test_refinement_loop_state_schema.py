"""Phase 48 Plan 48-01 — REQ-48-D3. RefinementLoopState 15-field schema."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.contracts.schemas import RefinementLoopState


def _base_kwargs(**overrides):
    now = datetime.now(timezone.utc)
    base = dict(
        loop_id="loop_001",
        root_hypothesis_id="hyp_001",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash_abc",
        iteration=0,
        max_iterations=3,
        iteration_artifact_ids=[],
        strategy_version="0.1.0",
        code_version="0.1.0",
        critic_history=[],
        veto_history=[],
        identity_scores=[],
        refinement_delta_history=[],
        budget_snapshot={"loop_total_usd": 0.0},
        termination_reason=None,
        started_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return base


def test_refinement_loop_state_round_trip() -> None:
    """All fields round-trip; list and dict structures preserved."""
    state = RefinementLoopState(
        **_base_kwargs(
            iteration=2,
            iteration_artifact_ids=[
                {"iter": 0, "strategy_spec_id": "ss_0"},
                {"iter": 1, "strategy_spec_id": "ss_1"},
            ],
            critic_history=["cv_0", "cv_1"],
            identity_scores=[1.0, 0.85],
            budget_snapshot={"loop_total_usd": 1.23, "iteration_usd": 0.45},
        )
    )
    rehydrated = RefinementLoopState.model_validate(state.model_dump(mode="json"))
    assert rehydrated.loop_id == "loop_001"
    assert rehydrated.iteration == 2
    assert len(rehydrated.iteration_artifact_ids) == 2
    assert rehydrated.iteration_artifact_ids[0]["strategy_spec_id"] == "ss_0"
    assert rehydrated.critic_history == ["cv_0", "cv_1"]
    assert rehydrated.identity_scores == [1.0, 0.85]
    assert rehydrated.budget_snapshot["loop_total_usd"] == pytest.approx(1.23)
    assert rehydrated.schema_version == 1


def test_refinement_loop_state_max_iterations_default_three() -> None:
    """max_iterations defaults to 3 (locked constant per CONTEXT § Decision 2)."""
    state = RefinementLoopState(**_base_kwargs())
    assert state.max_iterations == 3


def test_refinement_loop_state_rejects_extra_field() -> None:
    """extra='forbid'."""
    with pytest.raises(ValidationError):
        RefinementLoopState(**_base_kwargs(unknown_field="boom"))


def test_refinement_loop_state_termination_reason_optional() -> None:
    """termination_reason starts None and accepts string set later."""
    state = RefinementLoopState(**_base_kwargs(termination_reason=None))
    assert state.termination_reason is None
