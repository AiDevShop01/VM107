"""Phase 47.3 — Pullback / Entry Quality evaluator (10 pts) tests.

Status semantics:
  pass:           Entry within 1 ATR of FVG OR M5 BOS line
  unclear:        Entry within 1.5 ATR
  fail:           Entry > 1.5 ATR away from any anchor
  not_available:  L6 (FVG) AND L2 (BOS) both missing OR ATR unknown

Plan 04 GREEN.
"""


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
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.liquidity_context import (
        GetLiquidityContextResponse,
        LiquidityData,
    )
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        LayerBars,
        PrimitivesData,
    )

    entry = 1.1000
    atr = 0.0010
    # FVG far away: 5 ATR from entry. BOS line also far.
    far_fvg = {"active": True, "midpoint": entry + 5 * atr}
    far_bos = {"event_type": "BOS", "direction": "up", "price": entry + 6 * atr}

    liquidity_m5 = GetLiquidityContextResponse(
        status="ok",
        data=LiquidityData(
            instrument="EURUSD",
            timeframe="M5",
            fvg_zones=[far_fvg],
            equal_highs=[],
            equal_lows=[],
            imbalance_zones=[],
        ),
        meta=None,
    )

    primitives_m5 = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(
            instrument="EURUSD",
            timeframe="M5",
            layers=[
                LayerBars(
                    layer=1,
                    count=3,
                    bars=[
                        {"open": entry, "close": entry + 0.0001, "atr_short": atr},
                        {"open": entry + 0.0001, "close": entry + 0.0002, "atr_short": atr},
                        {"open": entry + 0.0002, "close": entry + 0.0003, "atr_short": atr},
                    ],
                ),
                LayerBars(layer=2, count=1, bars=[far_bos]),
            ],
        ),
        meta=None,
    )

    ctx = EvaluationContext(
        journal_id="fail-pull",
        instrument="EURUSD",
        direction="long",
        entry_price=entry,
        primitives_m5=primitives_m5,
        liquidity_m5=liquidity_m5,
    )
    result = evaluate_pullback(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 10


def test_pullback_not_available_when_anchors_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_pullback

    result = evaluate_pullback(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
