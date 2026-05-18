"""Phase 48 Plan 48-08a — REQ-48-D5 refinement_routing: STRATEGY_SPEC scope.

CONTEXT § Decision 5: a target whose scope == STRATEGY_SPEC causes Strategy
Agent to regenerate from the SAME immutable Hypothesis + targets, then
cascades into Code Agent. The cascade ordering (Strategy first, Code second)
is acyclic per CONTEXT § Decision 5.
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
        variables=["ema_fast", "ema_slow"],
        confidence=0.65,
    )


def _strategy_spec() -> StrategySpec:
    return StrategySpec(
        name="ema_breakout",
        features=["ema_fast", "ema_slow"],
        rules=["if ema_fast > ema_slow then BUY"],
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
        identity_score=0.85,
        registry_snapshot_hash="snapshot_test",
    )


def _strategy_target() -> RefinementTarget:
    return RefinementTarget(
        scope="STRATEGY_SPEC",
        canonical_issue_id="OVERFIT_SIGNATURE",
        target_field="rules",
        issue="entry too loose",
        issue_type="entry_filter",
        severity="HIGH",
        suggested_change="add ATR-based confirmation",
        source_critic_verdict_id="critic_prev",
    )


def test_strategy_scope_invokes_run_strategy_first_then_run_code(monkeypatch):
    """STRATEGY_SPEC scope: Strategy regenerated first, Code regenerated with NEW spec."""
    from core.agents.refinement_orchestrator import refinement_routing

    new_spec = _strategy_spec().model_copy(update={"version": "2.0.0"})
    new_code = _code_module().model_copy(update={"version": "2.0.0"})

    call_log: list[str] = []

    def fake_run_strategy(hypothesis, *, refinement_context=None, **_kw):
        call_log.append("run_strategy")
        return new_spec

    def fake_run_code(spec, *, refinement_context=None, **_kw):
        call_log.append("run_code")
        assert spec is new_spec, "run_code must receive the NEW spec from run_strategy"
        return new_code

    monkeypatch.setattr(refinement_routing, "run_strategy", fake_run_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", fake_run_code)

    targets = [_strategy_target()]
    out_spec, out_code = refinement_routing.route_refinement(
        targets=targets,
        prior_spec=_strategy_spec(),
        prior_code=_code_module(),
        hypothesis=_hypothesis(),
        envelope=_envelope(targets),
    )

    assert call_log == ["run_strategy", "run_code"], (
        f"Strategy must be regenerated before Code; got {call_log}"
    )
    assert out_spec is new_spec
    assert out_code is new_code


def test_strategy_scope_passes_envelope_to_both_wrappers(monkeypatch):
    """The envelope flows verbatim into BOTH wrappers via refinement_context kwarg."""
    from core.agents.refinement_orchestrator import refinement_routing

    new_spec = _strategy_spec().model_copy(update={"version": "2.0.0"})
    new_code = _code_module().model_copy(update={"version": "2.0.0"})
    captured: dict[str, RefinementContextEnvelope] = {}

    def fake_run_strategy(hypothesis, *, refinement_context=None, **_kw):
        captured["strategy"] = refinement_context
        return new_spec

    def fake_run_code(spec, *, refinement_context=None, **_kw):
        captured["code"] = refinement_context
        return new_code

    monkeypatch.setattr(refinement_routing, "run_strategy", fake_run_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", fake_run_code)

    targets = [_strategy_target()]
    env = _envelope(targets)
    refinement_routing.route_refinement(
        targets=targets,
        prior_spec=_strategy_spec(),
        prior_code=_code_module(),
        hypothesis=_hypothesis(),
        envelope=env,
    )

    assert captured["strategy"] is env
    assert captured["code"] is env
