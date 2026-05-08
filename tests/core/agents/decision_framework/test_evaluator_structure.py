"""Phase 47.3 — Structure evaluator (15 pts) tests.

Status semantics:
  pass:           M5 BOS in direction within last 20 bars
  unclear:        M5 CHoCH but no clean BOS
  fail:           Structure against direction (BOS counter-trend)
  not_available:  M5 primitives missing/empty

Plan 04 GREEN.
"""


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
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        LayerBars,
        PrimitivesData,
    )

    # Opposing-direction BOS (down BOS while direction=long).
    layer2 = LayerBars(
        layer=2,
        count=2,
        bars=[
            {"event_type": "BOS", "direction": "down", "price": 1.0950},
            {"event_type": "BOS", "direction": "down", "price": 1.0930},
        ],
    )
    primitives_m5 = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(instrument="EURUSD", timeframe="M5", layers=[layer2]),
        meta=None,
    )
    ctx = EvaluationContext(
        journal_id="fail-struct",
        instrument="EURUSD",
        direction="long",
        primitives_m5=primitives_m5,
    )
    result = evaluate_structure(ctx)
    assert result.status == "fail"
    assert result.score_contribution == 0
    assert result.max_points == 15


def test_structure_not_available_when_m5_missing(ctx_all_not_available):
    from core.agents.decision_framework.category_evaluators import evaluate_structure

    result = evaluate_structure(ctx_all_not_available)
    assert result.status == "not_available"
    assert result.score_contribution == 0
    assert result.max_points == 15
