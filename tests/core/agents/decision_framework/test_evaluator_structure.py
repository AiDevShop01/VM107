"""Phase 47.3 — Structure evaluator (15 pts) tests.

Status semantics:
  pass:           M5 BOS in direction within last 20 bars
  unclear:        M5 CHoCH but no clean BOS
  fail:           Structure against direction (BOS counter-trend)
  not_available:  M5 primitives missing/empty

Wave 0 — graduates in Plan 04 (evaluate_structure shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_structure not yet shipped (Plan 04)",
    strict=False,
)


def test_structure_pass_recent_bos(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_structure
    result = evaluate_structure(ctx_all_pass)
    assert result.name == "Structure"
    assert result.status == "pass"
    assert result.score_contribution == 15
    assert result.max_points == 15


def test_structure_unclear_choch_only(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_structure
    result = evaluate_structure(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 8


def test_structure_fail_counter_trend_bos():
    """M5 BOS counter to direction → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_structure
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_structure_not_available_when_m5_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_structure
    result = evaluate_structure(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 15
