"""Phase 47.3 — News / Macro evaluator (5 pts) tests.

Status semantics (V1):
  pass:           N/A in V1 (Tier-3 stubs only)
  unclear:        N/A in V1
  fail:           N/A in V1
  not_available:  ALWAYS in V1 — Tier-3 (news + macro) returns NotAvailableResponse

V1 rule: News=not_available drives -15 confidence (HIGH-tier capability).
Phase 47.4+ will swap stubs for real data; same evaluator function shape.

Wave 0 — graduates in Plan 04 (evaluate_news shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — evaluate_news not yet shipped (Plan 04)",
    strict=False,
)


def test_news_v1_always_not_available(ctx_all_pass):
    """V1 contract: News always returns not_available (Tier-3 stubs only)."""
    from core.agents.decision_framework.category_evaluators import evaluate_news
    result = evaluate_news(ctx_all_pass)
    assert result.name == "News"
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 5  # max_points stays — CONTEXT lock 4


def test_news_score_zero_when_not_available(ctx_partial_context):
    from core.agents.decision_framework.category_evaluators import evaluate_news
    result = evaluate_news(ctx_partial_context)
    assert result.status == "not_available"
    assert result.score_contribution == 0


def test_news_pass_path_reserved_for_v2():
    """V1 has no pass path. Plan 04 may include skip; once Tier-3 ships real
    feeds (Phase 47.4+), the pass path graduates."""
    from core.agents.decision_framework.category_evaluators import evaluate_news
    raise NotImplementedError("Phase 47.4+ V2 implements pass-path")


def test_news_not_available_drives_high_confidence_dock(ctx_partial_context):
    """When News is not_available, downstream confidence rule MUST dock -15
    (HIGH tier) for get_news_context capability."""
    from core.agents.decision_framework.framework import Framework
    result = Framework().run(ctx_partial_context)
    news_adjustments = [a for a in result.confidence_adjustments
                        if a.capability_id == "get_news_context"]
    assert any(a.impact == -15 and a.impact_tier == "HIGH"
               for a in news_adjustments)
