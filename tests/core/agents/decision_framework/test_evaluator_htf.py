"""Phase 47.3 — HTF/Bias evaluator (15 pts) tests.

Status semantics:
  pass:           H1 EMA20 slope matches direction AND last 3 H1 BOS in same direction
  unclear:        EMA aligned but recent CHoCH against direction
  fail:           EMA against direction OR opposite-direction BOS dominant
  not_available:  H1 primitives missing/empty

Plan 04 GREEN.
"""


def test_htf_pass_strong_alignment(ctx_all_pass):
    from core.agents.decision_framework.category_evaluators import evaluate_htf

    result = evaluate_htf(ctx_all_pass)
    assert result.name == "HTF"
    assert result.status == "pass"
    assert result.score_contribution == 15
    assert result.max_points == 15


def test_htf_unclear_recent_choch(ctx_mixed):
    from core.agents.decision_framework.category_evaluators import evaluate_htf

    result = evaluate_htf(ctx_mixed)
    assert result.status == "unclear"
    # unclear contributes 50% of max_points (rounded)
    assert result.score_contribution == 8


def test_htf_fail_against_direction():
    """H1 EMA against direction → fail."""
    from core.agents.decision_framework.category_evaluators import evaluate_htf
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        LayerBars,
        PrimitivesData,
    )

    # EMA20 sloping DOWN while direction=long → ema_aligned=False, no CHoCH → fail.
    ema_down = LayerBars(
        layer=11,
        count=5,
        bars=[
            {"ema20": 1.1000},
            {"ema20": 1.0980},
            {"ema20": 1.0960},
            {"ema20": 1.0940},
            {"ema20": 1.0920},
        ],
    )
    # Opposing-direction BOS (down BOS while direction=long).
    struct_against = LayerBars(
        layer=2,
        count=3,
        bars=[
            {"event_type": "BOS", "direction": "down", "price": 1.0950},
            {"event_type": "BOS", "direction": "down", "price": 1.0930},
            {"event_type": "BOS", "direction": "down", "price": 1.0910},
        ],
    )
    primitives_h1 = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(
            instrument="EURUSD", timeframe="H1", layers=[ema_down, struct_against]
        ),
        meta=None,
    )
    ctx = EvaluationContext(
        journal_id="fail-htf",
        instrument="EURUSD",
        direction="long",
        primitives_h1=primitives_h1,
    )
    result = evaluate_htf(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 15


def test_htf_not_available_when_h1_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_htf

    result = evaluate_htf(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 15  # max_points stays — CONTEXT lock 4
