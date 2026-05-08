"""Phase 47.3 — Liquidity evaluator (10 pts) tests.

Status semantics:
  pass:           Active FVG OR equal H/L within 1 ATR of entry
  unclear:        Zone within 1.5 ATR (close-but-not-quite)
  fail:           No relevant zone within 1.5 ATR
  not_available:  M15 liquidity context missing

Wave 0 — graduates in Plan 04 (evaluate_liquidity shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_liquidity not yet shipped (Plan 04)",
    strict=False,
)


def test_liquidity_pass_active_fvg(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_liquidity
    result = evaluate_liquidity(ctx_all_pass)
    assert result.name == "Liquidity"
    assert result.status == "pass"
    assert result.score_contribution == 10
    assert result.max_points == 10


def test_liquidity_unclear_close_zone(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_liquidity
    result = evaluate_liquidity(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 5


def test_liquidity_fail_no_zone():
    """No FVG / equal H-L within 1.5 ATR → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_liquidity
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_liquidity_not_available_when_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_liquidity
    result = evaluate_liquidity(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
