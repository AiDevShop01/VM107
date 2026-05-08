"""Phase 47.3 — Momentum/Displacement evaluator (15 pts) tests.

Status semantics:
  pass:           displacement body / ATR > 1.5
  unclear:        body / ATR in (1.0, 1.5]
  fail:           body / ATR <= 1.0
  not_available:  M5 primitives missing/empty

Wave 0 — graduates in Plan 04 (evaluate_momentum shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_momentum not yet shipped (Plan 04)",
    strict=False,
)


def test_momentum_pass_strong_displacement(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_momentum
    result = evaluate_momentum(ctx_all_pass)
    assert result.name == "Momentum"
    assert result.status == "pass"
    assert result.score_contribution == 15
    assert result.max_points == 15


def test_momentum_unclear_weak_displacement(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_momentum
    # ctx_mixed has body/atr ratio in (1.0, 1.5]
    result = evaluate_momentum(ctx_mixed)
    assert result.status == "unclear"
    # unclear contributes 50% of max_points (rounded)
    assert result.score_contribution == 8


def test_momentum_fail_no_displacement():
    """Body/ATR <= 1.0 → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_momentum
    raise NotImplementedError("Plan 04 fills in")


def test_momentum_not_available_when_m5_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_momentum
    result = evaluate_momentum(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 15  # max_points stays — CONTEXT lock 4
