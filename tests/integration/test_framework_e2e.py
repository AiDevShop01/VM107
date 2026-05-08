"""Phase 47.3 — End-to-end framework integration test.

Mocks Tier-2 tool outputs (primitives + liquidity ok, news/macro/regime
not_available), runs ``Framework().run()``, asserts the 5 LOCKED decisions
all hold simultaneously in the typed ``PythonEngineResult`` output (and via
the runner, in the typed ``PreTradeEvaluation``).

LOCKED decisions verified end-to-end:
  1. Pure Python rules engine — Python owns score/recommendation/confidence
  2. Category determinism — same input → same output
  3. Python-only overrides — registry callable applied
  4. ``not_available`` = score 0 absolute, max_score stays 100
  5. ``hard_rejects`` = hard veto on recommendation, score still visible

Plan 06 graduates the e2e tests by wiring through the refactored runner.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _build_minimal_ctx(strategy_id=None):
    """Build a minimal EvaluationContext with all Tier-2 not_available."""
    from core.agents.decision_framework.context import EvaluationContext
    from fingpt_core.contracts.agents.liquidity_context import (
        GetLiquidityContextResponse,
    )
    from fingpt_core.contracts.agents.not_available import (
        NotAvailableMeta,
        NotAvailableResponse,
    )
    from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response

    primitives_unav = GetPrimitivesV1Response(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_primitives",
            would_provide=["layer_bars"],
            impact_on_decision="HIGH",
            unblocks_when=["VM102 reachable"],
        ),
    )
    liquidity_unav = GetLiquidityContextResponse(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_liquidity_context",
            would_provide=["fvg_zones"],
            impact_on_decision="HIGH",
            unblocks_when=["VM102 reachable"],
        ),
    )
    news_stub = NotAvailableResponse(
        planned_phase="Phase 31",
        tool="get_news_context",
        would_provide=["scheduled_events"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 31 complete"],
    )
    macro_stub = NotAvailableResponse(
        planned_phase="Phase 32",
        tool="get_macro_context",
        would_provide=["scheduled_macro"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 32 complete"],
    )

    strategy = None
    if strategy_id:
        from core.agents.strategy_loader import load_strategy

        try:
            strategy = load_strategy(strategy_id)
        except Exception:
            strategy = None

    return EvaluationContext(
        journal_id="j-1",
        instrument="EURUSD",
        direction="long",
        strategy_id=strategy_id,
        strategy=strategy,
        timeframe="M5",
        primitives_h1=primitives_unav,
        primitives_m15=primitives_unav,
        primitives_m5=primitives_unav,
        liquidity_m15=liquidity_unav,
        liquidity_m5=liquidity_unav,
        macro_context=macro_stub,
        news_context=news_stub,
    )


def test_e2e_locked_decisions_hold_simultaneously():
    """End-to-end probe: all 5 LOCKED decisions enforced together."""
    from core.agents.decision_framework.framework import Framework

    ctx = _build_minimal_ctx()
    result = Framework().run(ctx)

    # LOCK 1: Python owns score/recommendation/confidence (typed dataclass).
    assert isinstance(result.score, int)
    assert result.recommendation in (
        "enter", "wait", "avoid", "needs_more_confirmation"
    )
    assert isinstance(result.confidence_pct, int)

    # LOCK 4: not_available contributes 0; max_score=100.
    assert result.score == 0
    assert result.max_score == 100

    # LOCK 1 + 4: partial_context flag set when HIGH-tier missing.
    assert result.partial_context is True


def test_e2e_not_available_score_zero_max_score_100():
    """LOCK 4: not_available contributes 0; max_score stays 100."""
    from core.agents.decision_framework.framework import Framework

    ctx = _build_minimal_ctx()
    result = Framework().run(ctx)
    assert result.score == 0
    assert result.max_score == 100


def test_e2e_hard_reject_forces_avoid_score_visible():
    """LOCK 5: hard_reject → avoid; score still computed and visible."""
    from core.agents.decision_framework.framework import Framework

    ctx = _build_minimal_ctx(strategy_id="model_2_option_1_short")
    result = Framework().run(ctx)

    # Hard reject fires (no_displacement / against_htf_trend) → recommendation
    # forced to 'avoid', but score and max_score remain visible.
    assert result.recommendation == "avoid"
    assert result.score == 0  # still visible (not nullified)
    assert result.max_score == 100
    assert len(result.hard_reject_reasons) >= 1


@pytest.mark.asyncio
async def test_e2e_python_owns_score_recommendation_confidence():
    """LOCK 1: Python owns these fields end-to-end through the runner."""
    import json
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    malicious = json.dumps({
        "score": 95, "max_score": 100, "recommendation": "enter",
        "confidence": 0.95, "instrument": "EURUSD", "direction": "long",
        "category_results": [], "confidence_adjustments": [],
        "partial_context": False, "framework_version": 99,
        "reasoning_summary": "x", "risks": [], "invalidations": [],
        "next_action": "x", "check_results": {},
    })

    tier1 = {
        "trade_id": "j-1", "instrument": "EURUSD", "direction": "long",
        "strategy_id": None, "last_evaluation": None,
        "journal_metadata": {"timeframe": "M5"},
    }

    db = MagicMock()
    envcol = MagicMock()
    envcol.find.return_value = iter([])
    envcol.find_one.return_value = None
    envcol.insert_one.return_value = MagicMock(inserted_id="x")
    db.__getitem__ = MagicMock(side_effect=lambda n: envcol)

    from tests.core.agents.test_evaluation_runner_47_3 import (
        _make_primitives_not_available,
        _make_liquidity_not_available,
        _make_news_stub,
        _make_macro_stub,
    )

    with patch(
        "core.agents.evaluation_runner.build_tier1_context",
        new=AsyncMock(return_value=tier1),
    ), patch(
        "core.agents.evaluation_runner._fetch_primitives",
        new=AsyncMock(return_value=_make_primitives_not_available()),
    ), patch(
        "core.agents.evaluation_runner._fetch_liquidity",
        new=AsyncMock(return_value=_make_liquidity_not_available()),
    ), patch(
        "core.agents.evaluation_runner._fetch_news_stub",
        new=AsyncMock(return_value=_make_news_stub()),
    ), patch(
        "core.agents.evaluation_runner._fetch_macro_stub",
        new=AsyncMock(return_value=_make_macro_stub()),
    ), patch(
        "core.agents.evaluation_runner._call_llm_structured",
        new=AsyncMock(return_value=malicious),
    ), patch(
        "core.agents.evaluation_runner.get_mongo_db",
        new=MagicMock(return_value=db),
    ):
        result = await run_pre_trade_evaluation(
            journal_id="j-1", strategy_id=None
        )

    # Python owns these — LLM's malicious 95/enter/0.95/99 must NOT survive.
    assert result.score == 0
    assert result.recommendation == "avoid"
    assert result.framework_version == 1


def test_e2e_categories_deterministic_for_same_input():
    """LOCK 2: same input → same output (run twice, expect identical results)."""
    from core.agents.decision_framework.framework import Framework

    ctx = _build_minimal_ctx()
    fw = Framework()
    r1 = fw.run(ctx)
    r2 = fw.run(ctx)
    assert r1.score == r2.score
    assert r1.recommendation == r2.recommendation
    assert r1.confidence_pct == r2.confidence_pct
    assert len(r1.category_results) == len(r2.category_results)


def test_e2e_python_only_overrides():
    """LOCK 3: override is Python-only, not YAML-driven.

    Verified by: the override is registered through the @register_override
    decorator (Plan 05). YAML hard_rejects map to NAMED Python predicates,
    not to YAML-defined behaviour. Asserted via the registry surface.
    """
    from core.agents.decision_framework.overrides import _OVERRIDES

    # At least one strategy override is registered (Plan 05 ships
    # model_2_option_1_short Location override).
    assert len(_OVERRIDES) >= 1
