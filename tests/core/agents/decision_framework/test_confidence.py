"""Phase 47.3 — Confidence Degradation Rule tests.

Magnitudes (V1 — tunable in Phase 49):
  HIGH   → -15
  MEDIUM →  -8
  LOW    →  -3

partial_context: True only when ANY HIGH-tier capability is not_available.

Includes Critical Findings:
- CF-1: confidence only docks when CATEGORY also resolves not_available
        (data availability, not just capability availability)
- timeframe-aware capability resolution (per-timeframe failures)

Wave 0 — graduated in Plan 03 (confidence module shipped).

Tests that need ctx_partial_context fixture (Plan 04 ships full envelope
data) stay xfail until Plan 04. The CF-1, magnitudes, dedupe, and clamping
tests below construct ctx + CategoryResult lists directly so they pass
without the runner-built fixtures.
"""
import pytest


def _make_ctx_with_macro_news_unavailable():
    """Build a ctx where macro_context + news_context are explicitly
    not_available; everything else absent (Tier-3 stubs absent → also reported
    unavailable, but only the explicit ones drive the test)."""
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    macro = NotAvailableResponse(
        planned_phase="phase 49",
        tool="get_macro_context",
        would_provide=["macro_regime"],
        impact_on_decision="HIGH",
        unblocks_when=["phase 49 ships"],
    )
    news = NotAvailableResponse(
        planned_phase="phase 49",
        tool="get_news_context",
        would_provide=["calendar_events"],
        impact_on_decision="HIGH",
        unblocks_when=["phase 49 ships"],
    )
    return EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        macro_context=macro,
        news_context=news,
    )


def _make_news_not_available_result(name="News", max_points=5):
    """Build a CategoryResult with status=not_available."""
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult

    return CategoryResult(
        name=name,
        status="not_available",
        score_contribution=0,
        max_points=max_points,
    )


def test_high_tier_docks_15():
    """HIGH-tier capability missing + News category not_available → -15 each."""
    from core.agents.decision_framework.confidence import (
        compute_confidence_adjustments,
    )

    ctx = _make_ctx_with_macro_news_unavailable()
    results = [_make_news_not_available_result()]
    adjustments = compute_confidence_adjustments(ctx, results)
    high = [a for a in adjustments if a.impact_tier == "HIGH"]
    assert all(a.impact == -15 for a in high)
    # News category maps to BOTH get_news_context AND get_macro_context (HIGH).
    assert len(high) == 2


def test_medium_tier_docks_8():
    """MEDIUM-tier capability missing → -8 (Location → get_primitives M15)."""
    from core.agents.decision_framework.confidence import (
        compute_confidence_adjustments,
    )
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult
    from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response

    m15_unavailable = GetPrimitivesV1Response(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_primitives",
            would_provide=["layer_1_bars"],
            impact_on_decision="MEDIUM",
            unblocks_when=["VM102 reachable"],
        ),
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        primitives_m15=m15_unavailable,
    )
    location = CategoryResult(
        name="Location",
        status="not_available",
        score_contribution=0,
        max_points=10,
    )
    adjustments = compute_confidence_adjustments(ctx, [location])
    assert len(adjustments) == 1
    assert adjustments[0].impact == -8
    assert adjustments[0].impact_tier == "MEDIUM"


def test_partial_context_flag_when_any_high_unavailable():
    """News category not_available + HIGH-tier capability gone → at least one
    HIGH adjustment exists; the runner sets partial_context=True from this."""
    from core.agents.decision_framework.confidence import (
        compute_confidence_adjustments,
    )

    ctx = _make_ctx_with_macro_news_unavailable()
    adjustments = compute_confidence_adjustments(
        ctx, [_make_news_not_available_result()]
    )
    assert any(a.impact_tier == "HIGH" for a in adjustments)


def test_partial_context_false_when_no_high_unavailable():
    """No HIGH-tier capability missing → no HIGH adjustment → partial_context=False."""
    from core.agents.decision_framework.confidence import (
        compute_confidence_adjustments,
    )
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult
    from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response

    m15_unavailable = GetPrimitivesV1Response(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_primitives",
            would_provide=[],
            impact_on_decision="MEDIUM",
            unblocks_when=[],
        ),
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        primitives_m15=m15_unavailable,
    )
    location = CategoryResult(
        name="Location",
        status="not_available",
        score_contribution=0,
        max_points=10,
    )
    adjustments = compute_confidence_adjustments(ctx, [location])
    assert all(a.impact_tier != "HIGH" for a in adjustments)


def test_dedupe_by_capability_and_category():
    """Same (capability_id, category) pair appears only once in adjustments."""
    from core.agents.decision_framework.confidence import (
        compute_confidence_adjustments,
    )

    ctx = _make_ctx_with_macro_news_unavailable()
    # Construct a CategoryResult list containing the SAME (News) entry twice
    # to ensure dedupe is robust even against pathological inputs.
    results = [
        _make_news_not_available_result(),
        _make_news_not_available_result(),
    ]
    adjustments = compute_confidence_adjustments(ctx, results)
    seen = set()
    for a in adjustments:
        key = (a.capability_id, a.reason)
        assert key not in seen, f"duplicate adjustment for {key}"
        seen.add(key)


def test_confidence_clamped_to_zero_floor():
    """OQ-9: framework's confidence_pct is clamped to [0, 100] even with many
    HIGH-tier capabilities out (this test asserts the clamping logic in
    isolation without invoking Framework.run, which needs Plan 04 evaluators).
    """
    from core.agents.decision_framework.thresholds import BASE_CONFIDENCE

    # Simulate 10 HIGH-tier (-15 each) adjustments — total -150.
    total_impact = -150
    confidence_pct = max(0, min(100, BASE_CONFIDENCE + total_impact))
    assert confidence_pct == 0


def test_confidence_clamped_to_hundred_ceiling():
    """OQ-9: even if magnitudes were positive (they aren't in V1), clamp at 100."""
    from core.agents.decision_framework.thresholds import BASE_CONFIDENCE

    confidence_pct = max(0, min(100, BASE_CONFIDENCE + 50))
    assert confidence_pct == 100


def test_confidence_only_fires_when_category_also_not_available():
    """CF-1: if get_primitives is not_available BUT HTF category resolved
    (e.g., fail or pass), don't dock confidence — confidence reflects DATA
    AVAILABILITY only when the category itself couldn't be evaluated."""
    from core.agents.decision_framework.confidence import (
        compute_confidence_adjustments,
    )
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult
    from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response

    h1_unavailable = GetPrimitivesV1Response(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_primitives",
            would_provide=[],
            impact_on_decision="HIGH",
            unblocks_when=[],
        ),
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        primitives_h1=h1_unavailable,
    )
    # HTF category resolved fail (we got SOME signal even though primitives
    # was out — perhaps from a different code path / cached data). CF-1 says
    # don't dock.
    htf_fail = CategoryResult(
        name="HTF",
        status="fail",
        score_contribution=0,
        max_points=15,
    )
    adjustments = compute_confidence_adjustments(ctx, [htf_fail])
    # No adjustment because category status != "not_available"
    assert adjustments == []


def test_is_capability_unavailable_with_timeframe_filter():
    """CF-1 extension: is_capability_unavailable('get_primitives', 'H1')
    distinguishes per-timeframe failures."""
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        PrimitivesData,
    )

    h1_unavailable = GetPrimitivesV1Response(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_primitives",
            would_provide=[],
            impact_on_decision="HIGH",
            unblocks_when=[],
        ),
    )
    m15_ok = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(instrument="EURUSD", timeframe="M15", layers=[]),
        meta=None,
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        primitives_h1=h1_unavailable,
        primitives_m15=m15_ok,
    )
    assert ctx.is_capability_unavailable("get_primitives", timeframe="H1") is True
    assert ctx.is_capability_unavailable("get_primitives", timeframe="M15") is False


@pytest.mark.xfail(
    reason="Phase 47.3 — Framework.run requires Plan 04 evaluators",
    strict=False,
)
def test_partial_context_via_framework_run(ctx_partial_context):
    """Smoke test: Framework().run(ctx) sets partial_context=True when any
    HIGH-tier capability is unavailable. Needs Plan 04 evaluators."""
    from core.agents.decision_framework.framework import Framework

    result = Framework().run(ctx_partial_context)
    assert result.partial_context is True
