"""Phase 47.3 — Strategy override registry.

LOCK 3: Python-only overrides — YAML stays simple; behavior lives in Python
callables registered via @register_override(strategy_id, category).

Wave 0 — graduates in Plan 03 (registry) + Plan 05 (Model 2 specifics).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — overrides module not yet shipped (Plan 03/05)",
    strict=False,
)


def test_register_override_decorator():
    from core.agents.decision_framework.overrides import (
        register_override, resolve_override, CategoryWeight,
    )

    @register_override("test_strat", "Momentum")
    def _override(ctx):
        return CategoryWeight(weight_multiplier=0.5, note="test")

    fn = resolve_override("test_strat", "Momentum")
    assert fn is not None


def test_resolve_override_returns_none_when_unregistered():
    from core.agents.decision_framework.overrides import resolve_override
    assert resolve_override("nonexistent", "Momentum") is None


def test_duplicate_override_registration_raises():
    from core.agents.decision_framework.overrides import (
        register_override, CategoryWeight,
    )

    @register_override("dup_strat", "Pullback")
    def _o1(ctx):
        return CategoryWeight()

    with pytest.raises(RuntimeError):
        @register_override("dup_strat", "Pullback")
        def _o2(ctx):
            return CategoryWeight()


def test_location_secondary_when_momentum_strong(ctx_override_applied):
    """Plan 05 ships the Model 2 Option 1 Short Location override.
    LOCK 3: weight halves max_points 10 → 5 when momentum is strong."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_override_applied)
    location = next(r for r in result.category_results if r.name == "Location")
    # max_points halved (10 → 5) — see CONTEXT decision 3
    assert location.max_points == 5
    assert location.override_applied is not None


def test_override_exception_skipped_with_log():
    """Plan 03: when override callable raises, framework MUST skip override and continue."""
    from core.agents.decision_framework.overrides import (
        register_override,
    )

    @register_override("crash_strat", "Momentum")
    def _crashing(ctx):
        raise RuntimeError("boom")

    # Plan 03 ships the try/except wrapper inside evaluator
    raise NotImplementedError("Plan 03/04 implements safe-call wrapper")


def test_override_cannot_change_status():
    """LOCK 3: override modifies WEIGHT/THRESHOLDS only — never flips status."""
    raise NotImplementedError("Plan 04/05 implements")


def test_override_weight_multiplier_max_1():
    """Risk 8: V1 rule — weight_multiplier <= 1.0; framework rejects > 1."""
    raise NotImplementedError("Plan 03 implements")
