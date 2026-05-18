"""Phase 48 Plan 48-08a — REQ-48-D11 accepted-strategy event emission.

CONTEXT § Decision 11: ``accept_strategy`` persists the doc into
``accepted_strategies`` + auto-generates the registry/strategy/<id>.yaml +
emits a ``strategy_accepted`` Phase 56 event. The emit MUST be atomic with
the persist (Pattern 51 — Plan 03 + Plan 07 lock).
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
        iteration_artifact_ids=[
            {"iter": 0, "strategy_spec_id": "spec0"},
            {"iter": 1, "strategy_spec_id": "spec1"},
            {"iter": 2, "strategy_spec_id": "spec2"},
        ],
        strategy_version="1.2.0",
        code_version="1.2.0",
        critic_history=["cv0", "cv1", "cv2"],
        veto_history=[],
        identity_scores=[1.0, 0.92, 0.91],
        refinement_delta_history=["d0", "d1"],
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
        confidence=0.91,
        refinement_targets=[],
        failure_modes=[],
        rationale="meets floor + critic ACCEPT",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id="cv2",
        registry_snapshot_hash="snapshot_test",
        schema_version=1,
    )


def _insert_loop_state(mongo_test_db, state: RefinementLoopState) -> None:
    doc = state.model_dump(mode="json")
    doc["_id"] = state.loop_id
    mongo_test_db["refinement_loops"].insert_one(doc)


def test_accept_strategy_inserts_accepted_doc(mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path):
    from core.agents.refinement_orchestrator import acceptance_path

    # Re-target the registry strategy dir to a tmp path so the test doesn't pollute the repo.
    monkeypatch.setattr(acceptance_path, "REGISTRY_STRATEGY_DIR", tmp_path)
    monkeypatch.setattr(acceptance_path, "emit_strategy_accepted", lambda **_kw: None)

    state = _state(loop_id="loop-acc-1", hyp_id=valid_hypothesis_id)
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

    assert isinstance(accepted_id, str) and accepted_id
    doc = mongo_test_db["accepted_strategies"].find_one({"accepted_strategy_id": accepted_id})
    assert doc is not None
    # CONTEXT § Decision 11 — 12-field doc shape.
    for key in [
        "accepted_strategy_id",
        "root_hypothesis_id",
        "strategy_family",
        "refinement_loop_id",
        "final_strategy_spec_id",
        "final_code_module_id",
        "final_backtest_result_id",
        "final_critic_verdict_id",
        "accepted_registry_snapshot_hash",
        "iteration_artifact_ids",
        "accepted_at",
        "accepted_by",
        "acceptance_reason",
        "schema_version",
    ]:
        assert key in doc, f"accepted_strategies doc missing field: {key}"
    assert doc["acceptance_reason"].startswith("CRITIC_ACCEPT_AT_ITER_")


def test_accept_strategy_emits_strategy_accepted_event(mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path):
    from core.agents.refinement_orchestrator import acceptance_path

    monkeypatch.setattr(acceptance_path, "REGISTRY_STRATEGY_DIR", tmp_path)

    captured: dict = {}

    def fake_emit(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(acceptance_path, "emit_strategy_accepted", fake_emit)

    state = _state(loop_id="loop-acc-evt", hyp_id=valid_hypothesis_id)
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

    assert captured["loop_id"] == "loop-acc-evt"
    assert captured["accepted_strategy_id"] == accepted_id
    assert captured["root_hypothesis_id"] == valid_hypothesis_id
    assert captured["final_iteration"] == 2
    # registry_yaml_path must point at the strategy YAML on disk.
    path = Path(captured["registry_yaml_path"])
    assert path.exists()
    assert path.parent == tmp_path
    assert path.name == f"{accepted_id}.yaml"


def test_accept_strategy_writes_registry_yaml(mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path):
    from core.agents.refinement_orchestrator import acceptance_path

    monkeypatch.setattr(acceptance_path, "REGISTRY_STRATEGY_DIR", tmp_path)
    monkeypatch.setattr(acceptance_path, "emit_strategy_accepted", lambda **_kw: None)

    state = _state(loop_id="loop-acc-yaml", hyp_id=valid_hypothesis_id)
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

    yaml_path = tmp_path / f"{accepted_id}.yaml"
    assert yaml_path.exists()
    text = yaml_path.read_text()
    assert "REGISTER_CAPABILITY" in text
    assert "type: strategy" in text
    assert "status: accepted" in text
    assert accepted_id in text
