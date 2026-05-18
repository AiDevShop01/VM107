"""Phase 48 Plan 48-08a — REQ-48-D6 orphan-rejection defensive contract.

CONTEXT § Decision 6: every refinement-loop artifact must trace back to a
root_hypothesis_id. Acceptance and rejection paths both depend on a present
RefinementLoopState (which itself ties to a hypothesis). The orphan check is
a defensive surface for ``run_refinement_loop`` callers that pass a missing
hypothesis_id or for direct-call abuses of the acceptance/rejection helpers
without going through the orchestrator.

This test pins:
  (a) ``assert_hypothesis_exists`` raises OrphanStrategyError on absent id.
  (b) accept_strategy + reject_strategy refuse to write if RefinementLoopState
      is missing for the provided loop_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.contracts.exceptions import OrphanStrategyError
from core.contracts.schemas import (
    CriticVerdict,
    RefinementLoopState,
)


def _state(loop_id: str = "loop-orphan", hyp_id: str = "hyp_phase48_test_001") -> RefinementLoopState:
    now = datetime.now(tz=timezone.utc)
    return RefinementLoopState(
        loop_id=loop_id,
        root_hypothesis_id=hyp_id,
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="snapshot_test",
        iteration=0,
        max_iterations=3,
        iteration_artifact_ids=[],
        strategy_version="1.0.0",
        code_version="1.0.0",
        critic_history=[],
        veto_history=[],
        identity_scores=[],
        refinement_delta_history=[],
        budget_snapshot={},
        termination_reason=None,
        started_at=now,
        updated_at=now,
        spec_iter0_id="spec_iter0",
        schema_version=1,
    )


def _verdict() -> CriticVerdict:
    return CriticVerdict(
        verdict="ACCEPT",
        confidence=0.85,
        refinement_targets=[],
        failure_modes=[],
        rationale="ok",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id=None,
        registry_snapshot_hash="snapshot_test",
        schema_version=1,
    )


def test_assert_hypothesis_exists_orphan_raises(mongo_test_db):
    from core.agents.refinement_orchestrator.acceptance_path import (
        assert_hypothesis_exists,
    )

    with pytest.raises(OrphanStrategyError):
        assert_hypothesis_exists(mongo_test_db, hypothesis_id="never_inserted")


def test_accept_strategy_refuses_when_loop_state_absent(mongo_test_db, valid_hypothesis_id, monkeypatch):
    """No RefinementLoopState row for the provided loop_id -> OrphanStrategyError."""
    from core.agents.refinement_orchestrator import acceptance_path

    # Mock emit_strategy_accepted so a defensive guard is the only thing that runs.
    monkeypatch.setattr(acceptance_path, "emit_strategy_accepted", lambda **_kw: None)

    state = _state(loop_id="loop-no-row", hyp_id=valid_hypothesis_id)
    final_iter_ids = {
        "strategy_spec_id": "spec_final",
        "code_module_id": "code_final",
        "backtest_result_id": "bt_final",
        "critic_verdict_id": "cv_final",
    }

    with pytest.raises(OrphanStrategyError):
        acceptance_path.accept_strategy(
            mongo_test_db,
            state=state,
            verdict=_verdict(),
            final_iteration_ids=final_iter_ids,
            final_iteration=0,
        )


def test_reject_strategy_refuses_when_loop_state_absent(mongo_test_db, valid_hypothesis_id, monkeypatch):
    """No RefinementLoopState row for the provided loop_id -> OrphanStrategyError."""
    from core.agents.refinement_orchestrator import rejection_path

    monkeypatch.setattr(rejection_path, "emit_strategy_rejected", lambda **_kw: None)

    state = _state(loop_id="loop-no-row", hyp_id=valid_hypothesis_id)

    with pytest.raises(OrphanStrategyError):
        rejection_path.reject_strategy(
            mongo_test_db,
            state=state,
            termination_reason="CRITIC_REJECT",
            verdict_or_none=_verdict(),
            final_iteration=0,
            iteration_artifact_ids=[],
        )
