"""Phase 47.3 — EvaluationContext Pydantic class tests.

Frozen, extra="forbid" — passed to every category evaluator.

Wave 0 — graduated in Plan 03 (context module shipped).
"""
import pytest


def test_evaluation_context_is_frozen():
    """OQ-2: model_config frozen=True."""
    from core.agents.decision_framework.context import EvaluationContext
    ctx = EvaluationContext(
        journal_id="j1", instrument="EURUSD", direction="long",
        strategy_id=None, strategy=None,
    )
    with pytest.raises(Exception):
        ctx.instrument = "USDJPY"  # frozen — must raise


def test_evaluation_context_extra_forbid():
    from pydantic import ValidationError
    from core.agents.decision_framework.context import EvaluationContext
    with pytest.raises(ValidationError):
        EvaluationContext(
            journal_id="j", instrument="X", direction="long",
            strategy_id=None, strategy=None, bogus_field="x",
        )


def test_is_capability_unavailable_recognises_not_available():
    """is_capability_unavailable('get_macro_context') returns True when
    ctx.macro_context is a NotAvailableResponse with status='not_available'."""
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    macro = NotAvailableResponse(
        planned_phase="phase 49",
        tool="get_macro_context",
        would_provide=["macro_regime"],
        impact_on_decision="HIGH",
        unblocks_when=["phase 49 ships"],
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        macro_context=macro,
    )
    assert ctx.is_capability_unavailable("get_macro_context") is True
    # And: stub absent → also reports unavailable (V1 stubs always n/a).
    assert ctx.is_capability_unavailable("get_news_context") is True


def test_htf_layers_helper():
    """ctx.htf_layers() returns None when primitives_h1 is None."""
    from core.agents.decision_framework.context import EvaluationContext
    ctx = EvaluationContext(
        journal_id="j", instrument="EURUSD", direction="long",
    )
    assert ctx.htf_layers() is None
    assert ctx.mtf_layers() is None
    assert ctx.m5_layers() is None


def test_is_capability_unavailable_with_timeframe_filter():
    """CF-1: is_capability_unavailable('get_primitives', 'H1') vs ('get_primitives', 'M5')
    returns different results when only one timeframe envelope is unavailable."""
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
            would_provide=["layer_1_bars"],
            impact_on_decision="HIGH",
            unblocks_when=["VM102 reachable"],
        ),
    )
    m5_ok = GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(instrument="EURUSD", timeframe="M5", layers=[]),
        meta=None,
    )
    ctx = EvaluationContext(
        journal_id="j",
        instrument="EURUSD",
        direction="long",
        primitives_h1=h1_unavailable,
        primitives_m5=m5_ok,
    )
    assert ctx.is_capability_unavailable("get_primitives", timeframe="H1") is True
    assert ctx.is_capability_unavailable("get_primitives", timeframe="M5") is False
    # ANY-mode (no timeframe) returns True because at least one is unavailable.
    assert ctx.is_capability_unavailable("get_primitives") is True
