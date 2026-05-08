"""Phase 47.3 — Momentum/Displacement evaluator (15 pts) tests.

Status semantics:
  pass:           displacement body / ATR > 1.5
  unclear:        body / ATR in (1.0, 1.5]
  fail:           body / ATR <= 1.0
  not_available:  M5 primitives missing/empty

Plan 04 GREEN.
"""


def test_momentum_pass_strong_displacement(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_momentum

    result = evaluate_momentum(ctx_all_pass)
    assert result.name == "Momentum"
    assert result.status == "pass"
    assert result.score_contribution == 15
    assert result.max_points == 15


def test_momentum_unclear_weak_displacement(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_momentum

    result = evaluate_momentum(ctx_mixed)
    assert result.status == "unclear"
    # unclear contributes 50% of max_points (rounded)
    assert result.score_contribution == 8


def test_momentum_fail_no_displacement():
    """Body/ATR <= 1.0 → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_momentum
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        LayerBars,
        PrimitivesData,
    )

    fail_l1 = LayerBars(
        layer=1,
        count=2,
        bars=[
            {"open": 1.1000, "close": 1.1005, "atr_short": 0.0010},  # 0.5
            {"open": 1.1005, "close": 1.1003, "atr_short": 0.0010},  # 0.2
        ],
    )
    primitives_m5 = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(instrument="EURUSD", timeframe="M5", layers=[fail_l1]),
        meta=None,
    )
    ctx = EvaluationContext(
        journal_id="fail",
        instrument="EURUSD",
        direction="long",
        primitives_m5=primitives_m5,
    )
    result = evaluate_momentum(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 15


def test_momentum_not_available_when_m5_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_momentum

    result = evaluate_momentum(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 15  # max_points stays — CONTEXT lock 4
