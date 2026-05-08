"""Phase 47.3 — Hard reject predicate registration + dispatch + boot assertion.

Includes Critical Findings:
- CF-3: conservative-read when data missing
- CF-5: boot-time assertion (all YAML names registered)

Wave 0 — graduates in Plan 03/05 (hard_rejects module + Model 2 predicates).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — hard_rejects module not yet shipped (Plan 03/05)",
    strict=False,
)


def test_register_hard_reject_decorator():
    from core.agents.decision_framework.hard_rejects import (
        register_hard_reject, _HARD_REJECTS,
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


def test_boot_time_assertion_all_yaml_names_have_predicate():
    """CF-5 + Risk 6 + downstream contract: framework boot MUST fail fast if
    ANY hard_reject name in any strategy YAML lacks a registered predicate."""
    from core.agents.decision_framework.framework import Framework
    # Boot must succeed when the strategies/model_2_option_1_short.py module
    # registers ALL hard_rejects from model_2_option_1_short.yaml.
    Framework()  # MUST NOT raise


def test_predicate_returns_true_collects_name(ctx_hard_reject_fired):
    from core.agents.decision_framework.framework import Framework
    fw = Framework()
    result = fw.run(ctx_hard_reject_fired)
    assert "no displacement" in result.hard_reject_reasons


def test_predicate_conservative_read_when_data_missing():
    """CF-3: predicate that depends on Momentum status MUST treat
    not_available as 'hard_reject fires' (safety bias). Plan 05 implements."""
    from core.agents.decision_framework.framework import Framework
    # When Momentum=not_available, the no_displacement predicate MUST return True.
    raise NotImplementedError("Plan 05 ships the conservative-read predicate")


def test_predicate_exception_does_not_crash_evaluation():
    """A bug in a predicate must not veto evaluation — log + skip."""
    from core.agents.decision_framework.hard_rejects import detect_hard_rejects
    raise NotImplementedError("Plan 05 implements safe-call wrapper")
