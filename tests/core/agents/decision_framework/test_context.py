"""Phase 47.3 — EvaluationContext Pydantic class tests.

Frozen, extra="forbid" — passed to every category evaluator.

Wave 0 — graduates in Plan 03 (context module shipped).
"""
import pytest

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — EvaluationContext not yet shipped (Plan 03)",
    strict=False,
)


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
    ctx.macro_context is a NotAvailableResponse."""
    from core.agents.decision_framework.context import EvaluationContext  # noqa: F401
    raise NotImplementedError("Plan 03 ships fixture")


def test_htf_layers_helper():
    """ctx exposes a helper to fetch H1 EMA + BOS layers cleanly."""
    from core.agents.decision_framework.context import EvaluationContext  # noqa: F401
    raise NotImplementedError("Plan 03 ships fixture")
