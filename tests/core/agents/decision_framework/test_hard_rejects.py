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


@pytest.mark.xfail(
    reason="Phase 47.3 — Plan 05 ships predicates for model_2_option_1_short.yaml; "
    "boot-time assertion fires until then (Path A in Plan 03 RESEARCH)",
    strict=False,
)
def test_boot_time_assertion_all_yaml_names_have_predicate():
    """CF-5 + Risk 6 + downstream contract: framework boot MUST fail fast if
    ANY hard_reject name in any strategy YAML lacks a registered predicate.

    Until Plan 05 ships predicates for ``model_2_option_1_short.yaml`` (3
    hard_rejects: 'breakout into HVN', 'no displacement', 'against HTF
    trend'), Framework() raises RuntimeError. Plan 05 graduates this test."""
    from core.agents.decision_framework.framework import Framework

    Framework()  # MUST NOT raise — graduates with Plan 05


@pytest.mark.xfail(
    reason="Phase 47.3 — Plan 05 ships the conservative-read predicate",
    strict=False,
)
def test_predicate_conservative_read_when_data_missing():
    """CF-3: predicate that depends on Momentum status MUST treat
    not_available as 'hard_reject fires' (safety bias). Plan 05 implements."""
    from core.agents.decision_framework.framework import Framework  # noqa: F401
    raise NotImplementedError("Plan 05 ships the conservative-read predicate")
