"""Phase 48 Plan 48-08a — REQ-48-D5 refinement_routing: CODE_MODULE scope.

CONTEXT § Decision 5: a target whose scope == CODE_MODULE causes Code Agent
to regenerate from CURRENT StrategySpec + targets. StrategySpec is NOT
mutated — Code Agent NEVER infers strategy evolution.
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import (
    CodeModule,
    Hypothesis,
    RefinementContextEnvelope,
    RefinementTarget,
    StrategyFamily,
    StrategySpec,
)


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        hypothesis="EMA breakout on 1H momentum",
        variables=["ema_fast"],
        confidence=0.65,
    )


def _strategy_spec() -> StrategySpec:
    return StrategySpec(
        name="ema_breakout",
        features=["ema_fast"],
        rules=["if ema_fast > 0 then BUY"],
        timeframes=["1H"],
        version="1.0.0",
        strategy_family=StrategyFamily.BREAKOUT,
    )


def _code_module() -> CodeModule:
    return CodeModule(
        module_type="strategy",
        target_vm="vm101",
        contract="EMABreakoutContract",
        code="def run(): pass",
        tests="def test_run(): assert True",
        version="1.0.0",
    )


def _envelope(targets: list[RefinementTarget]) -> RefinementContextEnvelope:
    return RefinementContextEnvelope(
        iteration=1,
        prior_strategy_spec_id="spec_prev",
        prior_code_module_id="code_prev",
        prior_build_report_id="build_prev",
        prior_backtest_result_id="bt_prev",
        critic_verdict_id="critic_prev",
        refinement_targets=targets,
        identity_score=0.9,
        registry_snapshot_hash="snapshot_test",
    )


def _code_target() -> RefinementTarget:
    return RefinementTarget(
        scope="CODE_MODULE",
        canonical_issue_id="EXIT_TIMING_DELAYED",
        target_field="code",
        issue="exit logic off by one bar",
        issue_type="exit_timing",
        severity="MEDIUM",
        suggested_change="advance exit by one bar",
        source_critic_verdict_id="critic_prev",
    )


def test_code_scope_invokes_only_run_code_not_run_strategy(monkeypatch):
    """All-CODE_MODULE targets: run_strategy is NOT invoked; run_code IS."""
    from core.agents.refinement_orchestrator import refinement_routing

    prior_spec = _strategy_spec()
    new_code = _code_module().model_copy(update={"version": "2.0.0"})
    call_log: list[str] = []

    def fake_run_strategy(hypothesis, *, refinement_context=None, **_kw):
        call_log.append("run_strategy")
        raise AssertionError(
            "CODE_MODULE scope must NEVER invoke run_strategy (Decision 5)"
        )

    def fake_run_code(spec, *, refinement_context=None, **_kw):
        call_log.append("run_code")
        assert spec is prior_spec, "run_code must receive the UNCHANGED prior spec"
        return new_code

    monkeypatch.setattr(refinement_routing, "run_strategy", fake_run_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", fake_run_code)

    targets = [_code_target()]
    out_spec, out_code = refinement_routing.route_refinement(
        targets=targets,
        prior_spec=prior_spec,
        prior_code=_code_module(),
        hypothesis=_hypothesis(),
        envelope=_envelope(targets),
    )

    assert call_log == ["run_code"], (
        f"CODE_MODULE-only scope must skip Strategy; got {call_log}"
    )
    # StrategySpec must be passed through unchanged.
    assert out_spec is prior_spec
    assert out_code is new_code


def test_code_scope_passes_envelope_only_to_run_code(monkeypatch):
    from core.agents.refinement_orchestrator import refinement_routing

    prior_spec = _strategy_spec()
    new_code = _code_module().model_copy(update={"version": "2.0.0"})
    captured: dict[str, RefinementContextEnvelope] = {}

    def fake_run_strategy(*_a, **_kw):
        raise AssertionError("CODE_MODULE scope must not call run_strategy")

    def fake_run_code(spec, *, refinement_context=None, **_kw):
        captured["code"] = refinement_context
        return new_code

    monkeypatch.setattr(refinement_routing, "run_strategy", fake_run_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", fake_run_code)

    targets = [_code_target()]
    env = _envelope(targets)
    refinement_routing.route_refinement(
        targets=targets,
        prior_spec=prior_spec,
        prior_code=_code_module(),
        hypothesis=_hypothesis(),
        envelope=env,
    )

    assert captured["code"] is env
