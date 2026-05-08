"""Phase 47.3 — Pullback / Entry Quality evaluator (10 pts) tests.

Status semantics:
  pass:           Entry within 1 ATR of FVG OR M5 BOS line
  unclear:        Entry within 1.5 ATR
  fail:           Entry > 1.5 ATR away from any anchor
  not_available:  L6 (FVG) AND L2 (BOS) both missing

Wave 0 — graduates in Plan 04 (evaluate_pullback shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_pullback not yet shipped (Plan 04)",
    strict=False,
)


def test_pullback_pass_close_to_anchor(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_pullback
    result = evaluate_pullback(ctx_all_pass)
    assert result.name == "Pullback"
    assert result.status == "pass"
    assert result.score_contribution == 10
    assert result.max_points == 10


def test_pullback_unclear_close_but_not_quite(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_pullback
    result = evaluate_pullback(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 5


def test_pullback_fail_far_from_anchors():
    """Entry > 1.5 ATR from any FVG / BOS line → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_pullback
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_pullback_not_available_when_anchors_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_pullback
    result = evaluate_pullback(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
