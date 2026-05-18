"""Phase 48 Plan 48-01 Task 1.3 — typed wrapper tests.

Tests run_code / run_build / run_backtest / run_critic + run_strategy gains
refinement_context kwarg. Mocks the underlying agent invocation primitive
(`_call_subordinate_sync` for LLM-mediated wrappers; the build_agent module
for the deterministic run_build).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.contracts.schemas import (
    BacktestMetrics,
    BacktestResult,
    BuildReport,
    CodeModule,
    CriticVerdict,
    Hypothesis,
    RefinementContextEnvelope,
    RefinementLoopState,
    StrategyFamily,
    StrategySpec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hypothesis() -> Hypothesis:
    return Hypothesis(
        hypothesis="momentum tends to persist in trending markets",
        variables=["rsi_14", "ema_20"],
        confidence=0.7,
    )


@pytest.fixture
def strategy_spec() -> StrategySpec:
    return StrategySpec(
        name="EMA Trend",
        features=["ema_20", "ema_50"],
        rules=["enter on golden cross"],
        timeframes=["1h"],
        version="0.1.0",
        strategy_family=StrategyFamily.TREND_CONTINUATION,
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
def backtest_result() -> BacktestResult:
    return BacktestResult(
        metrics=BacktestMetrics(win_rate=0.55, rr=1.8, max_drawdown=0.12),
        sample_size=250,
        confidence=0.85,
    )


@pytest.fixture
def build_report() -> BuildReport:
    return BuildReport(status="success", errors=[], warnings=[])


@pytest.fixture
def loop_state() -> RefinementLoopState:
    now = datetime.now(timezone.utc)
    return RefinementLoopState(
        loop_id="loop_001",
        root_hypothesis_id="hyp_001",
        strategy_family="TREND_CONTINUATION",
        loop_registry_snapshot_hash="hash_abc",
        iteration=1,
        strategy_version="0.1.0",
        code_version="0.1.0",
        started_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# run_strategy — refinement_context kwarg (additive; default None)
# ---------------------------------------------------------------------------


def test_run_strategy_accepts_refinement_context_kwarg(hypothesis, strategy_spec) -> None:
    """REQ-48-D5 — run_strategy(..., refinement_context=...) kwarg accepted (additive)."""
    from core.agents.invocation import run_strategy

    spec_json = strategy_spec.model_dump_json()
    env = RefinementContextEnvelope(
        iteration=1,
        prior_strategy_spec_id="ss_0",
        prior_code_module_id="cm_0",
        prior_build_report_id="br_0",
        prior_backtest_result_id="bt_0",
        critic_verdict_id="cv_0",
        refinement_targets=[],
        identity_score=0.95,
        registry_snapshot_hash="hash_abc",
    )
    with patch("core.agents.invocation._call_subordinate_sync", return_value=spec_json):
        result = run_strategy(hypothesis, refinement_context=env)
    assert isinstance(result, StrategySpec)


def test_run_strategy_default_refinement_context_none(hypothesis, strategy_spec) -> None:
    """Default None preserves Phase 44 call sites."""
    from core.agents.invocation import run_strategy

    spec_json = strategy_spec.model_dump_json()
    with patch("core.agents.invocation._call_subordinate_sync", return_value=spec_json):
        result = run_strategy(hypothesis)
    assert isinstance(result, StrategySpec)


# ---------------------------------------------------------------------------
# run_code
# ---------------------------------------------------------------------------


def test_run_code_returns_code_module(strategy_spec, code_module) -> None:
    from core.agents.invocation import run_code

    code_json = code_module.model_dump_json()
    with patch("core.agents.invocation._call_subordinate_sync", return_value=code_json):
        result = run_code(strategy_spec)
    assert isinstance(result, CodeModule)
    assert result.module_type == "strategy"


def test_run_code_accepts_refinement_context(strategy_spec, code_module) -> None:
    """run_code accepts optional refinement_context for code-scoped refinements."""
    from core.agents.invocation import run_code

    env = RefinementContextEnvelope(
        iteration=1,
        prior_strategy_spec_id="ss_0",
        prior_code_module_id="cm_0",
        prior_build_report_id="br_0",
        prior_backtest_result_id="bt_0",
        critic_verdict_id="cv_0",
        refinement_targets=[],
        identity_score=0.95,
        registry_snapshot_hash="hash_abc",
    )
    code_json = code_module.model_dump_json()
    with patch("core.agents.invocation._call_subordinate_sync", return_value=code_json):
        result = run_code(strategy_spec, refinement_context=env)
    assert isinstance(result, CodeModule)


def test_run_code_retries_once_then_fails(strategy_spec) -> None:
    """safe_parse retry-once-then-fail discipline."""
    from core.agents.invocation import run_code
    from core.agents.invocation_exceptions import CodeAgentDegradedError

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value="not valid json at all",
    ):
        with pytest.raises(CodeAgentDegradedError):
            run_code(strategy_spec)


# ---------------------------------------------------------------------------
# run_build — deterministic, NO LLM, NO retry
# ---------------------------------------------------------------------------


def test_run_build_returns_build_report_success(code_module, build_report) -> None:
    """run_build is a pure-Python service path — calls build_agent directly."""
    from core.agents.invocation import run_build

    with patch(
        "core.agents.invocation._invoke_build_agent",
        return_value=build_report,
    ):
        result = run_build(code_module)
    assert isinstance(result, BuildReport)
    assert result.status == "success"


def test_run_build_does_not_use_subordinate_sync(code_module, build_report) -> None:
    """run_build does NOT call _call_subordinate_sync (LLM path)."""
    from core.agents.invocation import run_build

    with patch(
        "core.agents.invocation._call_subordinate_sync"
    ) as mock_sub, patch(
        "core.agents.invocation._invoke_build_agent",
        return_value=build_report,
    ):
        run_build(code_module)
    assert mock_sub.call_count == 0


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------


def test_run_backtest_returns_backtest_result(code_module, backtest_result) -> None:
    from core.agents.invocation import run_backtest

    result_json = backtest_result.model_dump_json()
    with patch("core.agents.invocation._call_subordinate_sync", return_value=result_json):
        result = run_backtest(code_module)
    assert isinstance(result, BacktestResult)
    assert result.sample_size == 250


def test_run_backtest_retries_once_then_fails(code_module) -> None:
    from core.agents.invocation import run_backtest
    from core.agents.invocation_exceptions import BacktesterDegradedError

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value="garbage",
    ):
        with pytest.raises(BacktesterDegradedError):
            run_backtest(code_module)


# ---------------------------------------------------------------------------
# run_critic
# ---------------------------------------------------------------------------


def test_run_critic_returns_critic_verdict(
    loop_state, strategy_spec, code_module, build_report, backtest_result
) -> None:
    """run_critic uses safe_parse(CriticVerdict)."""
    from core.agents.invocation import run_critic

    verdict = CriticVerdict(
        verdict="ACCEPT",
        confidence=0.9,
        refinement_targets=[],
        failure_modes=[],
        rationale="strong",
        loaded_skills=["trend_continuation_critic"],
        source_critic_verdict_id=None,
        registry_snapshot_hash="hash_abc",
    )
    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=verdict.model_dump_json(),
    ):
        result = run_critic(
            loop_state, strategy_spec, code_module, build_report, backtest_result
        )
    assert isinstance(result, CriticVerdict)
    assert result.verdict == "ACCEPT"


def test_run_critic_retries_once_then_fails(
    loop_state, strategy_spec, code_module, build_report, backtest_result
) -> None:
    """Second degraded attempt raises CriticDegradedError (orchestrator handles)."""
    from core.agents.invocation import run_critic
    from core.agents.invocation_exceptions import CriticDegradedError

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value="not a verdict",
    ):
        with pytest.raises(CriticDegradedError):
            run_critic(
                loop_state, strategy_spec, code_module, build_report, backtest_result
            )
