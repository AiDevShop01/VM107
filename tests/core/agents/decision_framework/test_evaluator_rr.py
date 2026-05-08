"""Phase 47.3 — RR (Risk:Reward) evaluator (10 pts) tests.

Status semantics:
  pass:           planned_rr >= 1.5
  unclear:        planned_rr in [1.0, 1.5)
  fail:           planned_rr < 1.0
  not_available:  Journal lacks entry/stop/target — cannot compute

Plan 04 GREEN.
"""


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
    from core.agents.decision_framework.context import EvaluationContext

    ctx = EvaluationContext(
        journal_id="fail-rr",
        instrument="EURUSD",
        direction="long",
        entry_price=1.1000,
        stop_loss_price=1.0900,  # risk = 0.0100
        take_profit_price=1.1050,  # reward = 0.0050 → RR = 0.5
    )
    result = evaluate_rr(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 10


def test_rr_not_available_when_journal_missing(ctx_all_not_available):
    """No entry/stop/target in journal → not_available."""
    from core.agents.decision_framework.category_evaluators import evaluate_rr

    result = evaluate_rr(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
