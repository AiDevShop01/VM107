"""Phase 47.3 — Liquidity evaluator (10 pts) tests.

Status semantics:
  pass:           Active FVG OR equal H/L within 1 ATR of entry
  unclear:        Zone within 1.5 ATR (close-but-not-quite)
  fail:           No relevant zone within 1.5 ATR
  not_available:  M15 liquidity context missing

Plan 04 GREEN.
"""


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

    # FVG very far from entry (5 ATR away → fail)
    entry = 1.1000
    atr = 0.0010
    far_zone = {"active": True, "midpoint": entry + 5 * atr}

    liquidity_m15 = GetLiquidityContextResponse(
        status="ok",
        data=LiquidityData(
            instrument="EURUSD",
            timeframe="M15",
            fvg_zones=[far_zone],
            equal_highs=[],
            equal_lows=[],
            imbalance_zones=[],
        ),
        meta=None,
    )

    # Provide M5 L1 so _get_atr_from_m5 returns ~0.0010
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
                        {"open": 1.1000, "close": 1.1001, "atr_short": atr},
                        {"open": 1.1001, "close": 1.1002, "atr_short": atr},
                        {"open": 1.1002, "close": 1.1003, "atr_short": atr},
                    ],
                ),
            ],
        ),
        meta=None,
    )

    ctx = EvaluationContext(
        journal_id="fail-liq",
        instrument="EURUSD",
        direction="long",
        entry_price=entry,
        primitives_m5=primitives_m5,
        liquidity_m15=liquidity_m15,
    )
    result = evaluate_liquidity(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 10


def test_liquidity_not_available_when_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_liquidity

    result = evaluate_liquidity(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 10
