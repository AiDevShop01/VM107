"""Phase 47.3 — HTF/Bias evaluator (15 pts) tests.

Status semantics:
  pass:           H1 EMA20 slope matches direction AND last 3 H1 BOS in same direction
  unclear:        EMA aligned but recent CHoCH against direction
  fail:           EMA against direction OR opposite-direction BOS dominant
  not_available:  H1 primitives missing/empty

Wave 0 — graduates in Plan 04 (evaluate_htf shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_htf not yet shipped (Plan 04)",
    strict=False,
)


def test_htf_pass_strong_alignment(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_htf
    result = evaluate_htf(ctx_all_pass)
    assert result.name == "HTF"
    assert result.status == "pass"
    assert result.score_contribution == 15
    assert result.max_points == 15


def test_htf_unclear_recent_choch(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_htf
    result = evaluate_htf(ctx_mixed)
    assert result.status == "unclear"
    # unclear contributes 50% of max_points (rounded)
    assert result.score_contribution == 8


def test_htf_fail_against_direction():
    """H1 EMA against direction or opposite BOS dominant → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_htf
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_htf_not_available_when_h1_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_htf
    result = evaluate_htf(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 15  # max_points stays — CONTEXT lock 4
