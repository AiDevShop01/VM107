"""Phase 47.3 — Location evaluator (10 pts) tests.

Status semantics:
  pass:           Entry <= 50% of M15 swing range (premium for short / discount for long)
  unclear:        50-60% — borderline
  fail:           > 60% (poor location)
  not_available:  M15 primitives missing/empty

Wave 0 — graduates in Plan 04 (evaluate_location shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_location not yet shipped (Plan 04)",
    strict=False,
)


def test_location_pass_premium_or_discount(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_location
    result = evaluate_location(ctx_all_pass)
    assert result.name == "Location"
    assert result.status == "pass"
    assert result.score_contribution == 10
    assert result.max_points == 10


def test_location_unclear_borderline(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_location
    result = evaluate_location(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 5  # 50% of 10


def test_location_fail_poor_zone():
    """Entry > 60% of M15 swing range → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_location
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_location_not_available_when_m15_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_location
    result = evaluate_location(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
