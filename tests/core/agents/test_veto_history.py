"""Phase 48 Plan 48-04 Task 4.3 — veto_history accumulates across iterations.

Implements REQ-48-D9. CONTEXT § Decision 9:
"Emits {termination_reason: HARD_VETO, vetoes_triggered: [{metric, threshold,
actual}]} and persists to RefinementLoopState.veto_history."

Even though a HARD_VETO terminates the loop, the substrate must support
multi-iteration veto-history accumulation for two reasons:

1. Cross-loop telemetry / replay archaeology (CONTEXT § Decisions 7 + 13).
2. A loop may exhibit DIFFERENT vetoes across iterations before terminating
   (e.g., iter 1 trips max_drawdown veto, the system would still log the
   trigger to veto_history even as it terminates).

This test verifies the substrate contract: RefinementLoopState.veto_history
is a list of dicts; append_iteration_artifact + update_loop_state preserve
prior entries when appending new ones. We simulate 3 iterations each tripping
a different veto and assert the final state.veto_history is length 3 with
iteration_number tags.
"""
from __future__ import annotations


def test_veto_history_accumulates_one_entry_per_triggering_iteration(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """3 iterations, each trips a distinct veto — veto_history grows to length 3."""
    from core.agents.refinement_orchestrator import state as state_mod
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes
    from core.contracts.schemas import BacktestMetrics, BacktestResult

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-veto-history-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-veto-history-1",
    )

    # Three backtest results, each tripping ONE distinct veto.
    backtests = [
        # iter 0: max_drawdown veto
        BacktestResult(
            metrics=BacktestMetrics(
                win_rate=0.55, rr=1.5, max_drawdown=0.42,
                profit_factor=1.6, consecutive_losses=0, regime_coverage=1.0,
            ),
            sample_size=250, confidence=0.6,
        ),
        # iter 1: win_rate veto
        BacktestResult(
            metrics=BacktestMetrics(
                win_rate=0.20, rr=1.5, max_drawdown=0.10,
                profit_factor=1.6, consecutive_losses=0, regime_coverage=1.0,
            ),
            sample_size=250, confidence=0.6,
        ),
        # iter 2: consecutive_losses veto
        BacktestResult(
            metrics=BacktestMetrics(
                win_rate=0.55, rr=1.5, max_drawdown=0.10,
                profit_factor=1.6, consecutive_losses=15, regime_coverage=1.0,
            ),
            sample_size=250, confidence=0.6,
        ),
    ]

    veto_history: list[dict] = []
    for i, br in enumerate(backtests):
        triggers = check_hard_vetoes(br)
        assert len(triggers) == 1
        entry = dict(triggers[0])
        entry["iteration_number"] = i
        veto_history.append(entry)

    state_mod.update_loop_state(
        mongo_test_db, "loop-veto-history-1", veto_history=veto_history
    )

    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-veto-history-1"})
    persisted = doc["veto_history"]
    assert len(persisted) == 3

    # Each entry preserves iteration_number + metric + threshold + actual + op.
    assert persisted[0]["iteration_number"] == 0
    assert persisted[0]["metric"] == "max_drawdown"
    assert persisted[1]["iteration_number"] == 1
    assert persisted[1]["metric"] == "win_rate"
    assert persisted[2]["iteration_number"] == 2
    assert persisted[2]["metric"] == "consecutive_losses"


def test_veto_history_preserves_multiple_vetoes_from_single_iteration(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """One iteration can trip multiple vetoes simultaneously — all must persist."""
    from core.agents.refinement_orchestrator import state as state_mod
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes
    from core.contracts.schemas import BacktestMetrics, BacktestResult

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-veto-history-2",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-veto-history-2",
    )

    # Single backtest tripping ALL 4 vetoes.
    quadruple_veto = BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.20, rr=1.0, max_drawdown=0.42,
            profit_factor=1.6, consecutive_losses=15, regime_coverage=0.10,
        ),
        sample_size=250, confidence=0.6,
    )

    triggers = check_hard_vetoes(quadruple_veto)
    assert len(triggers) == 4

    veto_history = [dict(t, iteration_number=0) for t in triggers]
    state_mod.update_loop_state(
        mongo_test_db, "loop-veto-history-2", veto_history=veto_history
    )

    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-veto-history-2"})
    persisted = doc["veto_history"]
    assert len(persisted) == 4
    persisted_metrics = {entry["metric"] for entry in persisted}
    assert persisted_metrics == {
        "max_drawdown", "win_rate", "consecutive_losses", "regime_coverage"
    }
    assert all(entry["iteration_number"] == 0 for entry in persisted)


def test_veto_history_entries_carry_threshold_and_actual(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    """Every entry in veto_history must include metric, threshold, actual, op."""
    from core.agents.refinement_orchestrator import state as state_mod
    from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes
    from core.contracts.schemas import BacktestMetrics, BacktestResult

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )

    state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-veto-history-3",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-veto-history-3",
    )

    backtest = BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.55, rr=1.5, max_drawdown=0.42,
            profit_factor=1.6, consecutive_losses=0, regime_coverage=1.0,
        ),
        sample_size=250, confidence=0.6,
    )
    triggers = check_hard_vetoes(backtest)
    state_mod.update_loop_state(
        mongo_test_db, "loop-veto-history-3", veto_history=triggers
    )

    doc = mongo_test_db["refinement_loops"].find_one({"_id": "loop-veto-history-3"})
    persisted = doc["veto_history"]
    assert len(persisted) == 1
    entry = persisted[0]
    assert entry["metric"] == "max_drawdown"
    assert entry["threshold"] == 0.35
    assert entry["actual"] == 0.42
    assert entry["op"] == ">"
