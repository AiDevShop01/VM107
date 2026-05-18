"""Phase 48 Plan 48-08a — REQ-48-D5 refinement_routing: mixed scope (acyclic).

CONTEXT § Decision 5: mixed scope (>=1 STRATEGY_SPEC + >=1 CODE_MODULE) cascades
Strategy first, Code second — same dispatch as pure STRATEGY_SPEC because Code
ALWAYS regenerates downstream when Strategy mutates.
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
        hypothesis="EMA breakout on 1H",
        variables=["ema_fast"],
        confidence=0.6,
    )


def _strategy_spec() -> StrategySpec:
    return StrategySpec(
        name="ema_breakout",
        features=["ema_fast"],
        rules=["BUY on cross"],
        timeframes=["1H"],
        version="1.0.0",
        strategy_family=StrategyFamily.BREAKOUT,
    )


def _code_module() -> CodeModule:
    return CodeModule(
        module_type="strategy",
        target_vm="vm101",
        contract="C",
        code="x=1",
        tests="def test(): pass",
        version="1.0.0",
    )


def _strategy_target() -> RefinementTarget:
    return RefinementTarget(
        scope="STRATEGY_SPEC",
        canonical_issue_id="ENTRY_FILTER_TOO_LOOSE",
        target_field="rules",
        issue="tighten entry",
        issue_type="entry_filter",
        severity="HIGH",
        suggested_change="add RSI<30 confirmation",
        source_critic_verdict_id="critic_prev",
    )


def _code_target() -> RefinementTarget:
    return RefinementTarget(
        scope="CODE_MODULE",
        canonical_issue_id="EXIT_TIMING_DELAYED",
        target_field="code",
        issue="exit late",
        issue_type="exit_timing",
        severity="MEDIUM",
        suggested_change="advance exit",
        source_critic_verdict_id="critic_prev",
    )


def _envelope(targets: list[RefinementTarget]) -> RefinementContextEnvelope:
    return RefinementContextEnvelope(
        iteration=2,
        prior_strategy_spec_id="spec_prev",
        prior_code_module_id="code_prev",
        prior_build_report_id="build_prev",
        prior_backtest_result_id="bt_prev",
        critic_verdict_id="critic_prev",
        refinement_targets=targets,
        identity_score=0.82,
        registry_snapshot_hash="snapshot_test",
    )


def test_mixed_scope_invokes_strategy_first_then_code_with_new_spec(monkeypatch):
    """Mixed scope: Strategy regenerated first; Code receives the NEW spec, not prior."""
    from core.agents.refinement_orchestrator import refinement_routing

    prior_spec = _strategy_spec()
    new_spec = prior_spec.model_copy(update={"version": "2.0.0"})
    new_code = _code_module().model_copy(update={"version": "2.0.0"})
    call_log: list[str] = []

    def fake_run_strategy(hypothesis, *, refinement_context=None, **_kw):
        call_log.append("run_strategy")
        return new_spec

    def fake_run_code(spec, *, refinement_context=None, **_kw):
        call_log.append("run_code")
        assert spec is new_spec, (
            "Mixed-scope cascade must pass NEW spec to run_code (Decision 5)"
        )
        return new_code

    monkeypatch.setattr(refinement_routing, "run_strategy", fake_run_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", fake_run_code)

    targets = [_strategy_target(), _code_target()]
    out_spec, out_code = refinement_routing.route_refinement(
        targets=targets,
        prior_spec=prior_spec,
        prior_code=_code_module(),
        hypothesis=_hypothesis(),
        envelope=_envelope(targets),
    )

    assert call_log == ["run_strategy", "run_code"], (
        f"Mixed scope ordering must be Strategy-then-Code; got {call_log}"
    )
    assert out_spec is new_spec
    assert out_code is new_code


def test_mixed_scope_order_invariant_to_target_list_order(monkeypatch):
    """Mixed scope dispatch is order-invariant: Code-first target list still cascades Strategy first."""
    from core.agents.refinement_orchestrator import refinement_routing

    new_spec = _strategy_spec().model_copy(update={"version": "2.0.0"})
    new_code = _code_module().model_copy(update={"version": "2.0.0"})
    call_log: list[str] = []

    def fake_run_strategy(*_a, **_kw):
        call_log.append("run_strategy")
        return new_spec

    def fake_run_code(spec, *, refinement_context=None, **_kw):
        call_log.append("run_code")
        return new_code

    monkeypatch.setattr(refinement_routing, "run_strategy", fake_run_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", fake_run_code)

    # Targets supplied in CODE-first order; routing must still call Strategy first.
    targets = [_code_target(), _strategy_target()]
    refinement_routing.route_refinement(
        targets=targets,
        prior_spec=_strategy_spec(),
        prior_code=_code_module(),
        hypothesis=_hypothesis(),
        envelope=_envelope(targets),
    )

    assert call_log == ["run_strategy", "run_code"]
