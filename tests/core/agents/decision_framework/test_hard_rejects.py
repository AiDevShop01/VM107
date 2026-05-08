"""Phase 47.3 — Hard reject predicate registration + dispatch + boot assertion.

Includes Critical Findings:
- CF-3: conservative-read when data missing
- CF-5: boot-time assertion (all YAML names registered)

Wave 0 — graduated in Plan 03 (registry + dispatch + safe-call wrapper).
Boot-time assertion test stays xfail until Plan 05 ships predicates for
``model_2_option_1_short.yaml`` (Path A — see Plan 03 RESEARCH).
"""
import pytest


def test_register_hard_reject_decorator():
    from core.agents.decision_framework.hard_rejects import (
        _HARD_REJECTS,
        register_hard_reject,
    )

    @register_hard_reject("test_strategy", "no signal")
    def _predicate(ctx, results):
        return False

    assert ("test_strategy", "no signal") in _HARD_REJECTS


def test_duplicate_registration_raises():
    """Duplicate (strategy_id, name) registration is a programming error."""
    from core.agents.decision_framework.hard_rejects import register_hard_reject

    @register_hard_reject("dup_test", "x")
    def _p1(ctx, r):
        return False

    with pytest.raises(RuntimeError):
        @register_hard_reject("dup_test", "x")
        def _p2(ctx, r):
            return False


def test_is_hard_reject_registered():
    """is_hard_reject_registered reflects registry state."""
    from core.agents.decision_framework.hard_rejects import (
        is_hard_reject_registered,
        register_hard_reject,
    )

    assert is_hard_reject_registered("registry_check", "absent") is False

    @register_hard_reject("registry_check", "present")
    def _p(ctx, r):
        return False

    assert is_hard_reject_registered("registry_check", "present") is True


def test_detect_hard_rejects_returns_empty_when_no_strategy():
    """No strategy → no veto."""
    from core.agents.decision_framework.context import EvaluationContext
    from core.agents.decision_framework.hard_rejects import detect_hard_rejects

    ctx = EvaluationContext(
        journal_id="j", instrument="EURUSD", direction="long",
    )
    assert detect_hard_rejects(ctx, []) == []


def test_predicate_exception_does_not_crash_evaluation():
    """A bug in a predicate must not veto evaluation — log + skip."""
    from core.agents.decision_framework.context import EvaluationContext
    from core.agents.decision_framework.hard_rejects import (
        detect_hard_rejects,
        register_hard_reject,
    )
    from fingpt_core.contracts.agents.strategy_definition import (
        HardReject,
        StrategyDefinition,
    )

    @register_hard_reject("crash_strat", "buggy_check")
    def _buggy(ctx, results):
        raise RuntimeError("boom")

    strategy = StrategyDefinition(
        id="crash_strat",
        version=1,
        criteria=[],
        hard_rejects=[HardReject(name="buggy_check")],
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        strategy_id="crash_strat",
        strategy=strategy,
    )
    # Must not raise; predicate exception is logged + skipped → no hits.
    assert detect_hard_rejects(ctx, []) == []


def test_predicate_returns_true_collects_name():
    """When a predicate returns True, its name is in the hits list."""
    from core.agents.decision_framework.context import EvaluationContext
    from core.agents.decision_framework.hard_rejects import (
        detect_hard_rejects,
        register_hard_reject,
    )
    from fingpt_core.contracts.agents.strategy_definition import (
        HardReject,
        StrategyDefinition,
    )

    @register_hard_reject("fire_strat", "always_fires")
    def _fires(ctx, results):
        return True

    strategy = StrategyDefinition(
        id="fire_strat",
        version=1,
        criteria=[],
        hard_rejects=[HardReject(name="always_fires")],
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        strategy_id="fire_strat",
        strategy=strategy,
    )
    hits = detect_hard_rejects(ctx, [])
    assert "always_fires" in hits


def test_boot_time_assertion_all_yaml_names_have_predicate():
    """CF-5 + Risk 6 + downstream contract: framework boot MUST fail fast if
    ANY hard_reject name in any strategy YAML lacks a registered predicate.

    Plan 05 ships predicates for ``model_2_option_1_short.yaml`` (3
    hard_rejects: 'breakout into HVN', 'no displacement', 'against HTF
    trend') so ``Framework()`` boots cleanly."""
    from core.agents.decision_framework.framework import Framework

    Framework()  # MUST NOT raise — Plan 05 ships the 3 predicates


def test_predicate_conservative_read_when_data_missing():
    """CF-3: predicate that depends on Momentum status MUST treat
    not_available as 'hard_reject fires' (safety bias).

    With Momentum CategoryResult.status='not_available', the
    ``no displacement`` predicate must return True — we cannot confirm the
    REQUIRED setup invariant, and the strategy depends on displacement.
    Better to skip a real trade than execute one where the framework can't
    confirm the invariant. The alternative read (only fire on fail with real
    data) would mean partial-context evaluations bypass hard rejects
    entirely — a worse failure mode.
    """
    # Importing the strategy module triggers @register_hard_reject
    from core.agents.decision_framework.strategies import (
        model_2_option_1_short,  # noqa: F401
    )
    from core.agents.decision_framework.hard_rejects import _HARD_REJECTS
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult

    predicate = _HARD_REJECTS[("model_2_option_1_short", "no displacement")]

    # Build a Momentum CategoryResult with status='not_available' (data missing)
    momentum_na = CategoryResult(
        name="Momentum",
        status="not_available",
        score_contribution=0,
        max_points=15,
        threshold_used="M5 primitives missing",
    )
    by_name = {"Momentum": momentum_na}
    # CF-3 conservative read: missing data → fire the reject (safety bias).
    assert predicate(None, by_name) is True

    # Sanity check: Momentum=fail also fires (the 'real-data' fail path).
    momentum_fail = CategoryResult(
        name="Momentum",
        status="fail",
        score_contribution=0,
        max_points=15,
        threshold_used="peak_body_atr=0.5 <= 1.0",
    )
    assert predicate(None, {"Momentum": momentum_fail}) is True

    # Sanity check: Momentum=pass does NOT fire.
    momentum_pass = CategoryResult(
        name="Momentum",
        status="pass",
        score_contribution=15,
        max_points=15,
        threshold_used="peak_body_atr=1.85 > 1.5",
    )
    assert predicate(None, {"Momentum": momentum_pass}) is False
