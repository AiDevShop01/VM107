"""Phase 48 Plan 48-08a — REQ-48-D5 refinement_routing: validate_scope_combinations.

CONTEXT § Decision 5: orchestrator REJECTS invalid scope combinations at
validation time (e.g., CODE_MODULE target referencing strategy logic) via
``RefinementRoutingError``.

Invalid combinations:
  (a) CODE_MODULE-scoped target whose target_field exists ONLY in StrategySpec.
  (b) STRATEGY_SPEC-scoped target whose target_field exists ONLY in CodeModule.
  (c) Duplicate (target_field, scope) tuples in the same target list.

Field membership:
  StrategySpec-only: name, features, rules, timeframes, strategy_family
  CodeModule-only:   module_type, target_vm, contract, code, tests
  Shared:            version (legal in either scope)
  Nested:            metrics.*  (BacktestMetrics — neither model owns at the
                                 top-level Pydantic field set; allowed because
                                 Critic frequently routes metric-scoped concerns
                                 via STRATEGY_SPEC scope for parameter tuning.)
"""
from __future__ import annotations

import pytest

from core.contracts.exceptions import RefinementRoutingError
from core.contracts.schemas import RefinementTarget


def _target(scope: str, target_field: str, issue_id: str = "OVERFIT_SIGNATURE") -> RefinementTarget:
    return RefinementTarget(
        scope=scope,  # type: ignore[arg-type]
        canonical_issue_id=issue_id,  # type: ignore[arg-type]
        target_field=target_field,
        issue="x",
        issue_type="generic",
        severity="MEDIUM",
        suggested_change="adjust",
        source_critic_verdict_id="critic_prev",
    )


# ---------------------------------------------------------------------------
# (a) CODE_MODULE target referencing a StrategySpec-only field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strategy_only_field",
    ["name", "features", "rules", "timeframes", "strategy_family"],
)
def test_validate_rejects_code_module_target_on_strategy_only_field(strategy_only_field):
    """CODE_MODULE scope cannot target a field that only exists on StrategySpec."""
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    targets = [_target("CODE_MODULE", strategy_only_field)]
    with pytest.raises(RefinementRoutingError):
        validate_scope_combinations(targets)


# ---------------------------------------------------------------------------
# (b) STRATEGY_SPEC target referencing a CodeModule-only field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code_only_field",
    ["module_type", "target_vm", "contract", "code", "tests"],
)
def test_validate_rejects_strategy_spec_target_on_code_only_field(code_only_field):
    """STRATEGY_SPEC scope cannot target a field that only exists on CodeModule."""
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    targets = [_target("STRATEGY_SPEC", code_only_field)]
    with pytest.raises(RefinementRoutingError):
        validate_scope_combinations(targets)


# ---------------------------------------------------------------------------
# (c) Duplicate (target_field, scope) tuples
# ---------------------------------------------------------------------------


def test_validate_rejects_duplicate_field_scope_tuples():
    """The same (target_field, scope) pair appearing twice is a contract bug."""
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    targets = [
        _target("STRATEGY_SPEC", "rules"),
        _target("STRATEGY_SPEC", "rules"),
    ]
    with pytest.raises(RefinementRoutingError):
        validate_scope_combinations(targets)


# ---------------------------------------------------------------------------
# Positive: legal combinations pass.
# ---------------------------------------------------------------------------


def test_validate_accepts_legal_strategy_target():
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    # Must not raise.
    validate_scope_combinations([_target("STRATEGY_SPEC", "rules")])


def test_validate_accepts_legal_code_target():
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    validate_scope_combinations([_target("CODE_MODULE", "code")])


def test_validate_accepts_shared_version_field_on_either_scope():
    """``version`` exists on BOTH StrategySpec and CodeModule — legal either way."""
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    validate_scope_combinations([_target("STRATEGY_SPEC", "version")])
    validate_scope_combinations([_target("CODE_MODULE", "version")])


def test_validate_accepts_mixed_scope_with_distinct_field_scope_pairs():
    from core.agents.refinement_orchestrator.refinement_routing import (
        validate_scope_combinations,
    )

    targets = [
        _target("STRATEGY_SPEC", "rules"),
        _target("CODE_MODULE", "code"),
    ]
    # Must not raise.
    validate_scope_combinations(targets)


def test_route_refinement_invokes_validation_first(monkeypatch):
    """route_refinement validates scope before invoking any wrapper.

    An invalid scope combo must raise BEFORE run_strategy / run_code execute.
    """
    from core.agents.refinement_orchestrator import refinement_routing
    from core.contracts.schemas import (
        CodeModule,
        Hypothesis,
        RefinementContextEnvelope,
        StrategyFamily,
        StrategySpec,
    )

    def boom_strategy(*_a, **_kw):
        raise AssertionError("validation must run BEFORE run_strategy")

    def boom_code(*_a, **_kw):
        raise AssertionError("validation must run BEFORE run_code")

    monkeypatch.setattr(refinement_routing, "run_strategy", boom_strategy)
    monkeypatch.setattr(refinement_routing, "run_code", boom_code)

    invalid = [_target("CODE_MODULE", "rules")]  # rules is StrategySpec-only
    prior_spec = StrategySpec(
        name="x",
        features=["f"],
        rules=["BUY"],
        timeframes=["1H"],
        version="1.0.0",
        strategy_family=StrategyFamily.BREAKOUT,
    )
    prior_code = CodeModule(
        module_type="strategy",
        target_vm="vm101",
        contract="C",
        code="x=1",
        tests="def t(): pass",
        version="1.0.0",
    )
    env = RefinementContextEnvelope(
        iteration=1,
        prior_strategy_spec_id="s",
        prior_code_module_id="c",
        prior_build_report_id="b",
        prior_backtest_result_id="bt",
        critic_verdict_id="cv",
        refinement_targets=invalid,
        identity_score=0.9,
        registry_snapshot_hash="hash",
    )
    hyp = Hypothesis(hypothesis="abcdefghij", variables=["v"], confidence=0.5)

    with pytest.raises(RefinementRoutingError):
        refinement_routing.route_refinement(
            targets=invalid,
            prior_spec=prior_spec,
            prior_code=prior_code,
            hypothesis=hyp,
            envelope=env,
        )
