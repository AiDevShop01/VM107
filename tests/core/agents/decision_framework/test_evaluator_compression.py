"""Phase 47.3 — Compression/Pause evaluator (10 pts) tests.

Status semantics:
  pass:           L4 range_contraction_score >= 0.7 in last 8 M5 bars
  unclear:        L4 score in (0.4, 0.7)
  fail:           L4 score <= 0.4 (range expansion, not contraction)
  not_available:  L4 primitives missing/empty

Wave 0 — graduates in Plan 04 (evaluate_compression shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_compression not yet shipped (Plan 04)",
    strict=False,
)


def test_compression_pass_strong_contraction(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_compression
    result = evaluate_compression(ctx_all_pass)
    assert result.name == "Compression"
    assert result.status == "pass"
    assert result.score_contribution == 10
    assert result.max_points == 10


def test_compression_unclear_borderline(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_compression
    result = evaluate_compression(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 5


def test_compression_fail_range_expansion():
    """L4 contraction score <= 0.4 → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_compression
    raise NotImplementedError("Plan 04 fills in fail-case context build")


def test_compression_not_available_when_l4_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_compression
    result = evaluate_compression(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
