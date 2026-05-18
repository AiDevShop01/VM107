"""Phase 48 Plan 48-04 — every iteration persists BOTH deterministic_acceptance_result AND critic_verdict.

Implements REQ-48-D8 (telemetry + Critic calibration substrate).

CONTEXT § Decision 8 final bullet: "Persist BOTH deterministic_acceptance_result
AND critic_verdict on every iteration (telemetry + critic calibration substrate)."

Plan 48-04 ships acceptance_floor + hard_vetoes as pure functions. The main
orchestrator loop (Plan 08b) wires them. This test asserts the iteration-artifact
bundle CONTRACT: a single iteration must stamp BOTH `deterministic_acceptance_result_id`
AND `critic_verdict_id` (alongside the other 4 standard artifact ids) into
RefinementLoopState.iteration_artifact_ids[].

Because Plan 08b's main_loop is still a NotImplementedError stub, this test
exercises the contract by directly invoking the substrate primitives:
classify_acceptance -> append_iteration_artifact with both ids stamped. The
assertion is that the persisted bundle contains both keys. Plan 08b will use
this same contract.
"""
from __future__ import annotations


def test_iteration_artifact_bundle_persists_both_acceptance_and_critic_ids(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """A single iteration's artifact bundle must contain BOTH:
    - deterministic_acceptance_result_id
    - critic_verdict_id
    plus the 4 standard ids (strategy_spec_id, code_module_id,
    build_report_id, backtest_result_id).
    """
    from core.agents.refinement_orchestrator import state as state_mod
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance
    from core.contracts.schemas import BacktestMetrics, BacktestResult

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    # 1. Initialize loop state (Plan 03 substrate).
    state = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-completeness-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-completeness-1",
    )

    # 2. Simulate iteration 0 backtest + acceptance classification (pure function).
    backtest = BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.55, rr=1.5, max_drawdown=0.10, profit_factor=1.6
        ),
        sample_size=250,
        confidence=0.6,
    )
    acceptance = classify_acceptance(backtest)
    assert acceptance.passed is True  # sanity — feeds the bundle

    # 3. Stamp the iteration-0 bundle with BOTH acceptance_id + critic_verdict_id.
    #    Plan 08b's main_loop will do this; here we exercise the contract directly.
    bundle = {
        "iter": 0,
        "strategy_spec_id": "spec-0",
        "code_module_id": "code-0",
        "build_report_id": "build-0",
        "backtest_result_id": "bt-0",
        "deterministic_acceptance_result_id": "accept-0",
        "critic_verdict_id": "critic-0",
        "agent_envelope_ids": [],
    }
    state_mod.append_iteration_artifact(
        mongo_test_db, "loop-completeness-1", iteration=0, bundle=bundle
    )

    # 4. Reload from Mongo and assert the bundle contains BOTH stamping keys.
    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-completeness-1"})
    assert doc is not None
    artifacts = doc["iteration_artifact_ids"]
    assert len(artifacts) == 1
    stamped = artifacts[0]
    assert stamped["deterministic_acceptance_result_id"] == "accept-0"
    assert stamped["critic_verdict_id"] == "critic-0"
    # The 4 standard ids must also be present (no regression).
    assert stamped["strategy_spec_id"] == "spec-0"
    assert stamped["code_module_id"] == "code-0"
    assert stamped["build_report_id"] == "build-0"
    assert stamped["backtest_result_id"] == "bt-0"


def test_multiple_iterations_each_persist_both_ids(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """The completeness contract holds for EVERY iteration, not just iter 0.

    Three simulated iterations -> three bundles each stamping both ids.
    """
    from core.agents.refinement_orchestrator import state as state_mod

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-completeness-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-completeness-2",
    )

    for i in range(3):
        bundle = {
            "iter": i,
            "strategy_spec_id": f"spec-{i}",
            "code_module_id": f"code-{i}",
            "build_report_id": f"build-{i}",
            "backtest_result_id": f"bt-{i}",
            "deterministic_acceptance_result_id": f"accept-{i}",
            "critic_verdict_id": f"critic-{i}",
            "agent_envelope_ids": [],
        }
        state_mod.append_iteration_artifact(
            mongo_test_db, "loop-completeness-2", iteration=i, bundle=bundle
        )

    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-completeness-2"})
    artifacts = doc["iteration_artifact_ids"]
    assert len(artifacts) == 3
    for i, stamped in enumerate(artifacts):
        assert stamped["deterministic_acceptance_result_id"] == f"accept-{i}"
        assert stamped["critic_verdict_id"] == f"critic-{i}"
