"""Phase 48 Plan 48-08a — REQ-48-D12 rejection event emission + doc shape.

CONTEXT § Decision 12: ``reject_strategy`` persists a doc into the
``rejected_strategies`` WORM collection AND emits a ``strategy_rejected``
Phase 56 event (Pattern 51 atomic-with-persist).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contracts.schemas import CriticVerdict, RefinementLoopState


def _state(loop_id: str, hyp_id: str, *, veto_history=None) -> RefinementLoopState:
    now = datetime.now(tz=timezone.utc)
    return RefinementLoopState(
        loop_id=loop_id,
        root_hypothesis_id=hyp_id,
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="snapshot_test",
        iteration=2,
        max_iterations=3,
        iteration_artifact_ids=[
            {"iter": 0, "strategy_spec_id": "s0"},
            {"iter": 1, "strategy_spec_id": "s1"},
            {"iter": 2, "strategy_spec_id": "s2"},
        ],
        strategy_version="1.0.0",
        code_version="1.0.0",
        critic_history=["cv0", "cv1", "cv2"],
        veto_history=veto_history or [],
        identity_scores=[1.0, 0.9, 0.85],
        refinement_delta_history=["d0", "d1"],
        budget_snapshot={},
        termination_reason=None,
        started_at=now,
        updated_at=now,
        spec_iter0_id="s0",
        schema_version=1,
    )


def _verdict(verdict: str = "REJECT") -> CriticVerdict:
    return CriticVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=0.5,
        refinement_targets=[],
        failure_modes=["NO_EDGE"],
        rationale="no edge detected",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id="cv2",
        registry_snapshot_hash="snapshot_test",
        schema_version=1,
    )


def _insert_loop_state(mongo_test_db, state: RefinementLoopState) -> None:
    doc = state.model_dump(mode="json")
    doc["_id"] = state.loop_id
    mongo_test_db["refinement_loops"].insert_one(doc)


def test_reject_strategy_inserts_rejected_doc(mongo_test_db, valid_hypothesis_id, monkeypatch):
    from core.agents.refinement_orchestrator import rejection_path

    monkeypatch.setattr(rejection_path, "emit_strategy_rejected", lambda **_kw: None)

    state = _state(loop_id="loop-rej-insert", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    rejected_id = rejection_path.reject_strategy(
        mongo_test_db,
        state=state,
        termination_reason="CRITIC_REJECT",
        verdict_or_none=_verdict(),
        final_iteration=2,
        iteration_artifact_ids=list(state.iteration_artifact_ids),
    )

    assert isinstance(rejected_id, str) and rejected_id
    doc = mongo_test_db["rejected_strategies"].find_one({"rejected_strategy_id": rejected_id})
    assert doc is not None
    # CONTEXT § Decision 12 — 12-field doc.
    for key in [
        "rejected_strategy_id",
        "root_hypothesis_id",
        "strategy_family",
        "refinement_loop_id",
        "termination_reason",
        "iteration_count",
        "final_identity_score",
        "final_critic_verdict_id",
        "veto_history",
        "refinement_history",
        "iteration_artifact_ids",
        "registry_snapshot_hash",
        "rejected_at",
        "failure_surface_summary",
        "schema_version",
    ]:
        assert key in doc, f"rejected_strategies doc missing: {key}"
    assert doc["_worm_locked"] is True


def test_reject_strategy_emits_strategy_rejected_event(
    mongo_test_db, valid_hypothesis_id, monkeypatch
):
    from core.agents.refinement_orchestrator import rejection_path

    captured: dict = {}

    def fake_emit(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(rejection_path, "emit_strategy_rejected", fake_emit)

    state = _state(loop_id="loop-rej-evt", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    rejected_id = rejection_path.reject_strategy(
        mongo_test_db,
        state=state,
        termination_reason="MAX_ITERATIONS",
        verdict_or_none=_verdict("REFINE"),
        final_iteration=3,
        iteration_artifact_ids=list(state.iteration_artifact_ids),
    )

    assert captured["loop_id"] == "loop-rej-evt"
    assert captured["rejected_strategy_id"] == rejected_id
    assert captured["root_hypothesis_id"] == valid_hypothesis_id
    assert captured["termination_reason"] == "MAX_ITERATIONS"
    assert captured["final_iteration"] == 3


def test_reject_strategy_emits_event_when_verdict_is_none(
    mongo_test_db, valid_hypothesis_id, monkeypatch
):
    """Termination paths like HARD_VETO / BUDGET_EXCEEDED may have no Critic verdict."""
    from core.agents.refinement_orchestrator import rejection_path

    captured: dict = {}

    def fake_emit(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(rejection_path, "emit_strategy_rejected", fake_emit)

    state = _state(
        loop_id="loop-rej-noverdict",
        hyp_id=valid_hypothesis_id,
        veto_history=[{"metric": "max_drawdown", "threshold": 0.35, "actual": 0.42}],
    )
    _insert_loop_state(mongo_test_db, state)

    rejected_id = rejection_path.reject_strategy(
        mongo_test_db,
        state=state,
        termination_reason="HARD_VETO",
        verdict_or_none=None,
        final_iteration=0,
        iteration_artifact_ids=list(state.iteration_artifact_ids),
    )

    doc = mongo_test_db["rejected_strategies"].find_one({"rejected_strategy_id": rejected_id})
    assert doc is not None
    assert doc["final_critic_verdict_id"] is None
    assert doc["termination_reason"] == "HARD_VETO"
    assert captured["termination_reason"] == "HARD_VETO"


@pytest.mark.parametrize(
    "termination_reason",
    [
        "HARD_VETO",
        "IDENTITY_DRIFT",
        "CONVERGENCE_STALL",
        "BUDGET_EXCEEDED_ITERATION",
        "BUDGET_EXCEEDED_LOOP",
        "MAX_ITERATIONS",
        "CRITIC_REJECT",
        "BUILD_FAILURE",
        "BUILD_FAILED",
    ],
)
def test_reject_strategy_event_for_each_termination_reason(
    mongo_test_db, valid_hypothesis_id, monkeypatch, termination_reason
):
    """Each of the 9 termination reasons round-trips through emit_strategy_rejected."""
    from core.agents.refinement_orchestrator import rejection_path

    captured: dict = {}
    monkeypatch.setattr(
        rejection_path, "emit_strategy_rejected", lambda **kw: captured.update(kw)
    )

    state = _state(loop_id=f"loop-rej-{termination_reason}", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    rejection_path.reject_strategy(
        mongo_test_db,
        state=state,
        termination_reason=termination_reason,
        verdict_or_none=None,
        final_iteration=state.iteration,
        iteration_artifact_ids=list(state.iteration_artifact_ids),
    )

    assert captured["termination_reason"] == termination_reason
