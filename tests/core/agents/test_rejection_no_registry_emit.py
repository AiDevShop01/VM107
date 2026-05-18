"""Phase 48 Plan 48-08a — REQ-48-D12 rejection emits NO registry YAML.

CONTEXT § Decision 12: rejected strategies are first-class research-failure
cognition artifacts but they are NEVER registered as capabilities. No
``VM107/registry/strategy/<rejected_id>.yaml`` is written. The
acceptance/rejection split is load-bearing — capability surfaces are
strictly opt-in via promotion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.contracts.schemas import (
    CriticVerdict,
    RefinementLoopState,
)


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
            {"iter": 0, "strategy_spec_id": "s0"},
            {"iter": 1, "strategy_spec_id": "s1"},
            {"iter": 2, "strategy_spec_id": "s2"},
        ],
        strategy_version="1.0.0",
        code_version="1.0.0",
        critic_history=["cv0", "cv1", "cv2"],
        veto_history=[],
        identity_scores=[1.0, 0.9, 0.85],
        refinement_delta_history=["d0", "d1"],
        budget_snapshot={},
        termination_reason=None,
        started_at=now,
        updated_at=now,
        spec_iter0_id="s0",
        schema_version=1,
    )


def _verdict() -> CriticVerdict:
    return CriticVerdict(
        verdict="REJECT",
        confidence=0.55,
        refinement_targets=[],
        failure_modes=["NO_EDGE"],
        rationale="no edge",
        loaded_skills=["breakout_critic"],
        source_critic_verdict_id="cv2",
        registry_snapshot_hash="snapshot_test",
        schema_version=1,
    )


def _insert_loop_state(mongo_test_db, state: RefinementLoopState) -> None:
    doc = state.model_dump(mode="json")
    doc["_id"] = state.loop_id
    mongo_test_db["refinement_loops"].insert_one(doc)


def test_reject_strategy_does_not_emit_registry_yaml(
    mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path
):
    """rejection_path MUST NOT call strategy_yaml_emitter.emit_strategy_yaml."""
    from core.agents.refinement_orchestrator import rejection_path
    from core.registry import strategy_yaml_emitter

    call_count = {"n": 0}

    def boom_emit(*_a, **_kw):
        call_count["n"] += 1
        raise AssertionError(
            "rejection_path must NEVER call emit_strategy_yaml — rejected ≠ capability"
        )

    # Patch BOTH the symbol in the emitter module AND any potential import the
    # rejection module might hold (defensive: rejection_path should not import it at all).
    monkeypatch.setattr(strategy_yaml_emitter, "emit_strategy_yaml", boom_emit)
    monkeypatch.setattr(rejection_path, "emit_strategy_rejected", lambda **_kw: None)

    state = _state(loop_id="loop-rej-noreg", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    rejection_path.reject_strategy(
        mongo_test_db,
        state=state,
        termination_reason="CRITIC_REJECT",
        verdict_or_none=_verdict(),
        final_iteration=2,
        iteration_artifact_ids=list(state.iteration_artifact_ids),
    )

    assert call_count["n"] == 0


def test_reject_strategy_does_not_write_registry_strategy_file(
    mongo_test_db, valid_hypothesis_id, monkeypatch, tmp_path: Path
):
    """No file lands in the registry/strategy/ directory after a rejection."""
    from core.agents.refinement_orchestrator import rejection_path

    # If rejection_path accidentally calls the emitter, the file would appear
    # in tmp_path (since we redirect both the acceptance + emitter dirs there).
    from core.registry import strategy_yaml_emitter

    monkeypatch.setattr(
        strategy_yaml_emitter, "DEFAULT_REGISTRY_STRATEGY_DIR", tmp_path
    )
    monkeypatch.setattr(rejection_path, "emit_strategy_rejected", lambda **_kw: None)

    state = _state(loop_id="loop-rej-nofile", hyp_id=valid_hypothesis_id)
    _insert_loop_state(mongo_test_db, state)

    rejection_path.reject_strategy(
        mongo_test_db,
        state=state,
        termination_reason="CRITIC_REJECT",
        verdict_or_none=_verdict(),
        final_iteration=2,
        iteration_artifact_ids=list(state.iteration_artifact_ids),
    )

    files = list(tmp_path.iterdir())
    assert files == [], f"Rejection must not write to registry/strategy/; found: {files}"


def test_rejection_module_does_not_import_strategy_yaml_emitter():
    """AST-level guard: rejection_path.py must not import the emitter at all."""
    import ast
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "core"
        / "agents"
        / "refinement_orchestrator"
        / "rejection_path.py"
    ).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "strategy_yaml_emitter" not in mod, (
                f"rejection_path must not import strategy_yaml_emitter; "
                f"found 'from {mod} import ...' at line {node.lineno}"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "strategy_yaml_emitter" not in alias.name, (
                    f"rejection_path must not import strategy_yaml_emitter; "
                    f"found 'import {alias.name}' at line {node.lineno}"
                )
