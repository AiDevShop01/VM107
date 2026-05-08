"""Phase 47.3 — Location evaluator (10 pts) tests.

Status semantics:
  pass:           Entry <= 50% of M15 swing range (premium for short / discount for long)
  unclear:        50-60% — borderline
  fail:           > 60% (poor location)
  not_available:  M15 primitives missing/empty

Plan 04 GREEN.
"""


def test_location_pass_premium_or_discount(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_location

    result = evaluate_location(ctx_all_pass)
    assert result.name == "Location"
    assert result.status == "pass"
    assert result.score_contribution == 10
    assert result.max_points == 10


def test_location_unclear_borderline(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_location

    result = evaluate_location(ctx_mixed)
    assert result.status == "unclear"
    assert result.score_contribution == 5  # 50% of 10


def test_location_fail_poor_zone():
    """Entry > 60% of M15 swing range → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_location
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        LayerBars,
        PrimitivesData,
    )

    # range = 0.02; long entry near high (poor location)
    # entry = 1.1080 → discount = (1.1100 - 1.1080) / 0.02 = 0.10 (< 0.40 = fail)
    layer2 = LayerBars(
        layer=2,
        count=2,
        bars=[
            {"swing_high": 1.1100},
            {"swing_low": 1.0900},
        ],
    )
    primitives_m15 = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(instrument="EURUSD", timeframe="M15", layers=[layer2]),
        meta=None,
    )
    ctx = EvaluationContext(
        journal_id="fail-loc",
        instrument="EURUSD",
        direction="long",
        entry_price=1.1080,  # near high → poor discount
        primitives_m15=primitives_m15,
    )
    result = evaluate_location(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 10


def test_location_not_available_when_m15_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_location

    result = evaluate_location(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
