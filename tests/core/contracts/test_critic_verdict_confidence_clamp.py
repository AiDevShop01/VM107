"""Phase 48 Plan 06 — CriticVerdict.confidence HYBRID clamp.

CONTEXT § Decision 1 + planner Q7: the Critic emits a raw confidence value;
the orchestrator (run_critic wrapper) clamps it via a deterministic
derived_ceiling computed from backtest robustness signals.

Formula (planner-locked):
    sample_size_ratio = min(1.0, backtest_result.sample_size / 250)
    regime_coverage_ratio = backtest_result.metrics.regime_coverage
    derived_ceiling = 0.5 + 0.3 * sample_size_ratio + 0.2 * regime_coverage_ratio

The wrapper sets:
    verdict.confidence = min(raw_confidence, derived_ceiling)

Both raw and clamped values persist via the envelope output_payload.

REQ-48-D1.
"""
from __future__ import annotations

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
        loop_id="loop_clamp",
        root_hypothesis_id="hyp_clamp",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash_clamp",
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
        features=["atr_14"],
        rules=["enter long on breakout"],
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


def _make_backtest(sample_size: int, regime_coverage: float) -> BacktestResult:
    return BacktestResult(
        metrics=BacktestMetrics(
            win_rate=0.55,
            rr=1.8,
            max_drawdown=0.12,
            profit_factor=1.4,
            consecutive_losses=3,
            regime_coverage=regime_coverage,
        ),
        sample_size=sample_size,
        confidence=0.7,
    )


def _verdict_with_raw_confidence(raw: float) -> str:
    v = CriticVerdict(
        verdict="REFINE",
        confidence=raw,
        refinement_targets=[],
        failure_modes=[],
        rationale="testing clamp",
        loaded_skills=["breakout-critic"],
        registry_snapshot_hash="hash_clamp",
    )
    return v.model_dump_json()


def test_derived_confidence_ceiling_high_quality_backtest():
    """500 samples + 0.8 regime coverage -> ceiling = 0.5 + 0.3*1.0 + 0.2*0.8 = 0.96."""
    from core.agents.invocation import _derived_confidence_ceiling

    bt = _make_backtest(sample_size=500, regime_coverage=0.8)
    ceiling = _derived_confidence_ceiling(bt)
    assert ceiling == pytest.approx(0.96, abs=1e-9)


def test_derived_confidence_ceiling_low_quality_backtest():
    """50 samples + 0.2 regime coverage -> ceiling = 0.5 + 0.3*0.2 + 0.2*0.2 = 0.60."""
    from core.agents.invocation import _derived_confidence_ceiling

    bt = _make_backtest(sample_size=50, regime_coverage=0.2)
    ceiling = _derived_confidence_ceiling(bt)
    assert ceiling == pytest.approx(0.60, abs=1e-9)


def test_derived_confidence_ceiling_caps_sample_size_ratio_at_one():
    """Ratio is min(1, sample_size/250) — extreme oversampling does not exceed 1.0."""
    from core.agents.invocation import _derived_confidence_ceiling

    bt = _make_backtest(sample_size=10_000, regime_coverage=1.0)
    ceiling = _derived_confidence_ceiling(bt)
    assert ceiling == pytest.approx(1.0, abs=1e-9)


def test_run_critic_clamps_when_llm_overshoots_ceiling(
    loop_state, strategy_spec, code_module, build_report
):
    """Low-quality backtest forces clamp from LLM's 0.95 down to derived 0.60."""
    from core.agents.invocation import run_critic

    backtest = _make_backtest(sample_size=50, regime_coverage=0.2)
    raw_verdict_json = _verdict_with_raw_confidence(0.95)

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=raw_verdict_json,
    ):
        result = run_critic(
            loop_state, strategy_spec, code_module, build_report, backtest
        )

    assert result.confidence == pytest.approx(0.60, abs=1e-9)


def test_run_critic_does_not_clamp_when_llm_under_ceiling(
    loop_state, strategy_spec, code_module, build_report
):
    """High-quality backtest keeps LLM's 0.7 confidence (ceiling ~0.96)."""
    from core.agents.invocation import run_critic

    backtest = _make_backtest(sample_size=500, regime_coverage=0.8)
    raw_verdict_json = _verdict_with_raw_confidence(0.7)

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=raw_verdict_json,
    ):
        result = run_critic(
            loop_state, strategy_spec, code_module, build_report, backtest
        )

    assert result.confidence == pytest.approx(0.7, abs=1e-9)


def test_run_critic_persists_raw_confidence_alongside_clamped(
    loop_state, strategy_spec, code_module, build_report
):
    """When db is supplied, the envelope output_payload carries both
    `confidence` (clamped) and `raw_confidence` (LLM-emitted).
    """
    from core.agents.invocation import run_critic

    backtest = _make_backtest(sample_size=50, regime_coverage=0.2)
    raw_verdict_json = _verdict_with_raw_confidence(0.95)

    captured: list[dict] = []

    def _capture_build(**kwargs):
        # Echo back kwargs as an envelope dict — bypasses stamp_at_write_time
        # which requires an initialized CapabilityRegistry.
        captured.append(kwargs)
        return dict(kwargs)

    def _noop_write(db, envelope):
        return envelope

    with patch(
        "core.agents.invocation._call_subordinate_sync",
        return_value=raw_verdict_json,
    ), patch(
        "core.agents.envelope_writer.build_envelope", side_effect=_capture_build
    ), patch(
        "core.agents.envelope_writer.write_envelope", side_effect=_noop_write
    ):
        result = run_critic(
            loop_state,
            strategy_spec,
            code_module,
            build_report,
            backtest,
            db=object(),  # truthy non-None
        )

    assert result.confidence == pytest.approx(0.60, abs=1e-9)
    assert len(captured) == 1
    payload = captured[0]["output_payload"]
    assert payload["confidence"] == pytest.approx(0.60, abs=1e-9)
    assert payload["raw_confidence"] == pytest.approx(0.95, abs=1e-9)
    assert payload["derived_confidence_ceiling"] == pytest.approx(
        0.60, abs=1e-9
    )
