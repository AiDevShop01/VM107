"""Phase 47.3 — RR (Risk:Reward) evaluator (10 pts) tests.

Status semantics:
  pass:           planned_rr >= 1.5
  unclear:        planned_rr in [1.0, 1.5)
  fail:           planned_rr < 1.0
  not_available:  Journal lacks entry/stop/target — cannot compute

Wave 0 — graduates in Plan 04 (evaluate_rr shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_rr not yet shipped (Plan 04)",
    strict=False,
)


def test_rr_pass_strong_setup(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_rr
    result = evaluate_rr(ctx_all_pass)
    assert result.name == "RR"
    assert result.status == "pass"
    assert result.score_contribution == 10
    assert result.max_points == 10


def test_rr_unclear_marginal(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_rr
    result = evaluate_rr(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 5


def test_rr_fail_negative_setup():
    """planned_rr < 1.0 → fail (risk > reward)."""
    from core.agents.decision_framework.category_evaluators import evaluate_rr
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_rr_not_available_when_journal_missing(ctx_all_not_available):
    """No entry/stop/target in journal → not_available."""
    from core.agents.decision_framework.category_evaluators import evaluate_rr
    result = evaluate_rr(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
