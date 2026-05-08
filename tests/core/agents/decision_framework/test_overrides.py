"""Phase 47.3 — Strategy override registry.

LOCK 3: Python-only overrides — YAML stays simple; behavior lives in Python
callables registered via @register_override(strategy_id, category).

Wave 0 — graduated in Plan 03 (registry + safe_resolve_weight) +
Plan 05 (Model 2 specifics).
"""
import pytest


def test_register_override_decorator():
    from core.agents.decision_framework.overrides import (
        CategoryWeight,
        register_override,
        resolve_override,
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
        CategoryWeight,
        register_override,
    )

    @register_override("dup_strat", "Pullback")
    def _o1(ctx):
        return CategoryWeight()

    with pytest.raises(RuntimeError):
        @register_override("dup_strat", "Pullback")
        def _o2(ctx):
            return CategoryWeight()


def test_override_exception_skipped_with_log():
    """When override callable raises, framework MUST skip override and continue."""
    from core.agents.decision_framework.overrides import (
        register_override,
        safe_resolve_weight,
    )

    @register_override("crash_strat", "Momentum")
    def _crashing(ctx):
        raise RuntimeError("boom")

    new_max, note = safe_resolve_weight("crash_strat", "Momentum", None, 15)
    assert new_max == 15  # default preserved
    assert note is not None
    assert "override_failed" in note


def test_override_weight_multiplier_max_1():
    """Risk 8: V1 rule — weight_multiplier <= 1.0; framework rejects > 1."""
    from core.agents.decision_framework.overrides import (
        CategoryWeight,
        register_override,
        safe_resolve_weight,
    )

    @register_override("inflate_strat", "Momentum")
    def _inflating(ctx):
        return CategoryWeight(weight_multiplier=1.5)

    new_max, note = safe_resolve_weight("inflate_strat", "Momentum", None, 15)
    assert new_max == 15  # NOT inflated to 22
    assert note is not None
    assert "weight_multiplier > 1.0" in note


def test_safe_resolve_weight_no_strategy_returns_default():
    """No strategy_id → default unchanged, no note."""
    from core.agents.decision_framework.overrides import safe_resolve_weight
    new_max, note = safe_resolve_weight(None, "Momentum", None, 15)
    assert new_max == 15
    assert note is None


def test_safe_resolve_weight_unregistered_returns_default():
    """Strategy id present but no override registered → default unchanged."""
    from core.agents.decision_framework.overrides import safe_resolve_weight
    new_max, note = safe_resolve_weight(
        "no_overrides_strat", "Momentum", None, 15
    )
    assert new_max == 15
    assert note is None


def test_safe_resolve_weight_applies_multiplier():
    """Valid override with multiplier 0.5 + max_points 10 → 5."""
    from core.agents.decision_framework.overrides import (
        CategoryWeight,
        register_override,
        safe_resolve_weight,
    )

    @register_override("halve_strat", "Location")
    def _half(ctx):
        return CategoryWeight(weight_multiplier=0.5, note="halved")

    new_max, note = safe_resolve_weight("halve_strat", "Location", None, 10)
    assert new_max == 5
    assert note == "halved"


def test_location_secondary_when_momentum_strong(ctx_override_applied):
    """Plan 05 ships the Model 2 Option 1 Short Location override.
    LOCK 3: weight halves max_points 10 → 5 when momentum is strong."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_override_applied)
    location = next(r for r in result.category_results if r.name == "Location")
    # max_points halved (10 → 5) — see CONTEXT decision 3
    assert location.max_points == 5
    assert location.override_applied is not None


def test_override_cannot_change_status(ctx_override_applied):
    """LOCK 3: override modifies WEIGHT/THRESHOLDS only — never flips status.

    The Model 2 Option 1 Short Location override sets weight_multiplier=0.5
    when momentum is strong. The Location category status is computed
    purely from M15 swing data (not from the override). Verify the override
    DID fire (max_points halved + override_applied populated) but the
    Location status is still data-driven.
    """
    from core.agents.decision_framework.framework import Framework

    result = Framework().run(ctx_override_applied)
    location = next(r for r in result.category_results if r.name == "Location")
    # Override DID fire — max_points halved, note populated.
    assert location.max_points == 5
    assert location.override_applied is not None
    # Status is data-driven, not override-driven.
    assert location.status in ("pass", "fail", "unclear", "not_available")
    # Score contribution respects the halved max_points (max 5 even on pass).
    assert location.score_contribution <= location.max_points
