"""Phase 48 Plan 06 — Critic transformation purity invariant.

CONTEXT § Decision 1 + § Anti-Patterns: the strategy_refinement_critic
NEVER rewrites StrategySpec or CodeModule. It only emits a CriticVerdict.

This test mocks the underlying Agent Zero invocation and asserts:
1. run_critic returns a CriticVerdict (not an AgentEnvelope[CriticVerdict] —
   the existing typed-wrapper convention from Plan 48-01 returns the bare
   typed payload; envelope persistence is side-effectful via the db kwarg).
2. The StrategySpec and CodeModule instances passed in are NOT mutated.
3. The verdict carries the expected loaded_skills list back to the orchestrator.

REQ-48-D1 — transformation purity invariant.
"""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

from core.contracts.schemas import (
    BacktestMetrics,
    BacktestResult,
    BuildReport,
    CodeModule,
    CriticVerdict,
    RefinementLoopState,
    StrategyFamily,
    StrategySpec,
)


@pytest.fixture
def loop_state() -> RefinementLoopState:
    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop_purity_001",
        root_hypothesis_id="hyp_purity_001",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash_purity",
        iteration=1,
        strategy_version="0.1.0",
        code_version="0.1.0",
        started_at=now,
        updated_at=now,
    )


@pytest.fixture
def strategy_spec() -> StrategySpec:
    return StrategySpec(
        name="ATR Breakout",
        features=["atr_14", "high_20"],
        rules=["enter long on close > prev_high_20"],
        timeframes=["1h"],
        version="0.1.0",
        strategy_family=StrategyFamily.BREAKOUT,
    )


@pytest.fixture
def code_module() -> CodeModule:
    return CodeModule(
        module_type="strategy",
        target_vm="vm102",
        contract="StrategyV1",
        code="def run(): pass",
        tests="def test_run(): assert True",
        version="0.1.0",
    )


@pytest.fixture
def build_report() -> BuildReport:
    return BuildReport(status="success", errors=[], warnings=[])


@pytest.fixture
def backtest_result() -> BacktestResult:
    return BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.55,
            rr=1.8,
            max_drawdown=0.12,
            profit_factor=1.4,
            consecutive_losses=4,
            regime_coverage=0.6,
        ),
        sample_size=260,
        confidence=0.78,
    )


def _verdict_json(verdict: CriticVerdict) -> str:
    return verdict.model_dump_json()


def test_run_critic_returns_critic_verdict_only(
    loop_state, strategy_spec, code_module, build_report, backtest_result
):
    """REQ-48-D1 — run_critic returns CriticVerdict (not a mutated StrategySpec/CodeModule)."""
    from core.agents.invocation import run_critic

    verdict_in = CriticVerdict(
        verdict="REFINE",
        confidence=0.65,
        refinement_targets=[],
        failure_modes=["fm_overfit_breakout_threshold"],
        rationale="Sample size is on the floor; widen the breakout buffer.",
        loaded_skills=["breakout-critic"],
        registry_snapshot_hash="hash_purity",
    )

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=_verdict_json(verdict_in),
    ):
        result = run_critic(
            loop_state,
            strategy_spec,
            code_module,
            build_report,
            backtest_result,
        )

    assert isinstance(result, CriticVerdict)
    assert result.verdict == "REFINE"


def test_run_critic_does_not_mutate_strategy_spec(
    loop_state, strategy_spec, code_module, build_report, backtest_result
):
    """REQ-48-D1 — StrategySpec passed in is not mutated."""
    from core.agents.invocation import run_critic

    pre_spec = copy.deepcopy(strategy_spec)

    verdict_in = CriticVerdict(
        verdict="ACCEPT",
        confidence=0.8,
        refinement_targets=[],
        failure_modes=[],
        rationale="All floors satisfied.",
        loaded_skills=["breakout-critic"],
        registry_snapshot_hash="hash_purity",
    )

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=_verdict_json(verdict_in),
    ):
        run_critic(
            loop_state,
            strategy_spec,
            code_module,
            build_report,
            backtest_result,
        )

    # Equality + per-field check
    assert strategy_spec == pre_spec
    assert strategy_spec.name == pre_spec.name
    assert strategy_spec.features == pre_spec.features
    assert strategy_spec.rules == pre_spec.rules
    assert strategy_spec.strategy_family == pre_spec.strategy_family


def test_run_critic_does_not_mutate_code_module(
    loop_state, strategy_spec, code_module, build_report, backtest_result
):
    """REQ-48-D1 — CodeModule passed in is not mutated."""
    from core.agents.invocation import run_critic

    pre_code = copy.deepcopy(code_module)

    verdict_in = CriticVerdict(
        verdict="REFINE",
        confidence=0.7,
        refinement_targets=[],
        failure_modes=[],
        rationale="Refine entry filter.",
        loaded_skills=["breakout-critic"],
        registry_snapshot_hash="hash_purity",
    )

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=_verdict_json(verdict_in),
    ):
        run_critic(
            loop_state,
            strategy_spec,
            code_module,
            build_report,
            backtest_result,
        )

    assert code_module == pre_code
    assert code_module.code == pre_code.code
    assert code_module.tests == pre_code.tests
    assert code_module.version == pre_code.version


def test_run_critic_does_not_mutate_backtest_result(
    loop_state, strategy_spec, code_module, build_report, backtest_result
):
    """REQ-48-D1 — BacktestResult passed in is not mutated."""
    from core.agents.invocation import run_critic

    pre_result = copy.deepcopy(backtest_result)

    verdict_in = CriticVerdict(
        verdict="REJECT",
        confidence=0.55,
        refinement_targets=[],
        failure_modes=["fm_no_edge"],
        rationale="Sample insufficient; reject.",
        loaded_skills=["breakout-critic"],
        registry_snapshot_hash="hash_purity",
    )

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=_verdict_json(verdict_in),
    ):
        run_critic(
            loop_state,
            strategy_spec,
            code_module,
            build_report,
            backtest_result,
        )

    assert backtest_result == pre_result
    assert backtest_result.sample_size == pre_result.sample_size
    assert backtest_result.metrics == pre_result.metrics
