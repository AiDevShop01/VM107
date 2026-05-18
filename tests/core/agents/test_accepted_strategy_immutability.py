"""Phase 48 Plan 48-08a — REQ-48-D11 accepted-strategy WORM enforcement.

CONTEXT § Decision 11: accepted_strategies is **immutable WORM** — no editing,
no mutation, no "updating accepted strategy." The simplest V1 enforcement is
application-layer: a hidden ``_worm_locked: True`` flag stamped on insert
plus a guard helper ``assert_worm_locked_then_raise`` that the orchestrator
calls before any $set / $unset / $rename / replace_one on the collection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contracts.schemas import CriticVerdict, RefinementLoopState


def _state(loop_id: str, hyp_id: str) -> RefinementLoopState:
    now = datetime.now(tz=timezone.utc)
    return RefinementLoopState(
        loop_id=loop_id,
        root_hypothesis_id=hyp_id,
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="snapshot_test",
        iteration=2,
        max_iterations=3,
        iteration_artifact_ids=[],
        strategy_version="1.0.0",
        code_version="1.0.0",
        critic_history=["cv0", "cv1", "cv2"],
        veto_history=[],
        identity_scores=[1.0, 0.9, 0.91],
        refinement_delta_history=["d1"],
        budget_snapshot={},
        termination_reason=None,
        started_at=now,
        updated_at=now,
        spec_iter0_id="spec0",
        schema_version=1,
    )


def _verdict() -> CriticVerdict:
    return CriticVerdict(
        verdict="ACCEPT",
        confidence=0.92,
        refinement_targets=[],
        failure_modes=[],
        rationale="ok",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id="cv2",
        registry_snapshot_hash="snapshot_test",
        schema_version=1,
    )


def _insert_loop_state(mongo_test_db, state: RefinementLoopState) -> None:
    doc = state.model_dump(mode="json")
    doc["_id"] = state.loop_id
    mongo_test_db["refinement_loops"].insert_one(doc)


def test_accepted_doc_carries_worm_locked_flag_after_insert(
    mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path
):
    from core.agents.refinement_orchestrator import acceptance_path

    monkeypatch.setattr(acceptance_path, "REGISTRY_STRATEGY_DIR", tmp_path)
    monkeypatch.setattr(acceptance_path, "emit_strategy_accepted", lambda **_kw: None)

    state = _state(loop_id="loop-worm-1", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    final_ids = {
        "strategy_spec_id": "spec_final",
        "code_module_id": "code_final",
        "backtest_result_id": "bt_final",
        "critic_verdict_id": "cv2",
    }
    accepted_id = acceptance_path.accept_strategy(
        mongo_test_db,
        state=state,
        verdict=_verdict(),
        final_iteration_ids=final_ids,
        final_iteration=2,
    )
    doc = mongo_test_db["accepted_strategies"].find_one({"accepted_strategy_id": accepted_id})
    assert doc["_worm_locked"] is True


def test_worm_guard_blocks_mutation_attempt(mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path):
    """The application-layer guard raises when called against a worm-locked doc."""
    from core.agents.refinement_orchestrator import acceptance_path

    monkeypatch.setattr(acceptance_path, "REGISTRY_STRATEGY_DIR", tmp_path)
    monkeypatch.setattr(acceptance_path, "emit_strategy_accepted", lambda **_kw: None)

    state = _state(loop_id="loop-worm-2", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    final_ids = {
        "strategy_spec_id": "spec_final",
        "code_module_id": "code_final",
        "backtest_result_id": "bt_final",
        "critic_verdict_id": "cv2",
    }
    accepted_id = acceptance_path.accept_strategy(
        mongo_test_db,
        state=state,
        verdict=_verdict(),
        final_iteration_ids=final_ids,
        final_iteration=2,
    )

    with pytest.raises(RuntimeError):
        acceptance_path.assert_worm_locked_then_raise(
            mongo_test_db,
            collection="accepted_strategies",
            doc_id=accepted_id,
        )


def test_worm_guard_passes_on_unlocked_doc(mongo_test_db):
    """A doc inserted WITHOUT the WORM flag bypasses the guard (negative control)."""
    from core.agents.refinement_orchestrator import acceptance_path

    mongo_test_db["accepted_strategies"].insert_one(
        {"_id": "unlocked", "accepted_strategy_id": "unlocked"}
    )
    # Must not raise.
    acceptance_path.assert_worm_locked_then_raise(
        mongo_test_db,
        collection="accepted_strategies",
        doc_id="unlocked",
    )
