"""Phase 47.3 — evaluation_runner refactor tests.

CRITICAL: ``test_llm_cannot_override_framework_score`` is THE
Critical-Finding-2 probe. If it fails (LLM-supplied score wins), Phase 47.3's
deterministic guarantee is broken in one missing ``model_copy`` line.

These tests verify the refactored runner orchestration:

  Step 1 — _build_eval_context (Tier-1 + Tier-2 via asyncio.gather + Tier-3)
  Step 2 — Framework().run(ctx) → PythonEngineResult
  Step 3 — LLM call with framework_result block injected into messages
  Step 4 — model_copy(update={...}) overwrite Python-owned fields (CF-2)
  Step 5 — persist envelope
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure VM107 root is on sys.path before any module imports.
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_mock_db():
    """Minimal mock pymongo db that satisfies the runner's persistence path."""
    envelopes_col = MagicMock()
    envelopes_col.find.return_value = iter([])
    envelopes_col.find_one.return_value = None
    envelopes_col.insert_one.return_value = MagicMock(inserted_id="mongo-oid")
    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: envelopes_col
        if name == "agent_envelopes"
        else MagicMock()
    )
    db._col = envelopes_col
    return db


def _make_tier1_stub(instrument="EURUSD", direction="long", strategy_id=None):
    """Return a curated Tier-1 dict matching ``build_tier1_context`` shape."""
    return {
        "trade_id": "journal-1",
        "instrument": instrument,
        "direction": direction,
        "strategy_id": strategy_id,
        "last_evaluation": None,
        "journal_metadata": {
            "timeframe": "M5",
            "entry_price": 1.10,
            "stop_loss_price": 1.09,
            "take_profit_price": 1.13,
        },
    }


def _make_primitives_not_available():
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response

    return GetPrimitivesV1Response(
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


def _make_liquidity_not_available():
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.agents.liquidity_context import (
        GetLiquidityContextResponse,
    )

    return GetLiquidityContextResponse(
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


def _make_news_stub():
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    return NotAvailableResponse(
        planned_phase="Phase 31",
        tool="get_news_context",
        would_provide=["scheduled_events"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 31 complete"],
    )


def _make_macro_stub():
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    return NotAvailableResponse(
        planned_phase="Phase 32",
        tool="get_macro_context",
        would_provide=["scheduled_macro"],
        impact_on_decision="HIGH",
        unblocks_when=["Phase 32 complete"],
    )


def _malicious_llm_json(score=100, recommendation="enter", confidence=0.99):
    """Return a JSON string the LLM might emit attempting to override Python."""
    return json.dumps({
        "score": score,
        "max_score": 100,
        "recommendation": recommendation,
        "confidence": confidence,
        "instrument": "EURUSD",
        "direction": "long",
        "category_results": [],
        "confidence_adjustments": [],
        "partial_context": False,
        "framework_version": 99,
        "reasoning_summary": "Looks great!",
        "risks": ["llm-supplied-risk"],
        "invalidations": ["llm-supplied-invalidation"],
        "next_action": "enter now",
        "check_results": {"htf_alignment": "pass"},
    })


def _patch_runner_dependencies(
    *,
    llm_response: str,
    tier1=None,
    primitives=None,
    liquidity=None,
    news=None,
    macro=None,
):
    """Build a stack of patches for the 5-step runner pipeline.

    Returns a list of context-manager patches; the caller stacks them via
    ``contextlib.ExitStack``.
    """
    import contextlib

    if tier1 is None:
        tier1 = _make_tier1_stub()
    if primitives is None:
        primitives = _make_primitives_not_available()
    if liquidity is None:
        liquidity = _make_liquidity_not_available()
    if news is None:
        news = _make_news_stub()
    if macro is None:
        macro = _make_macro_stub()

    patches = [
        patch(
            "core.agents.evaluation_runner.build_tier1_context",
            new=AsyncMock(return_value=tier1),
        ),
        patch(
            "core.agents.evaluation_runner._fetch_primitives",
            new=AsyncMock(return_value=primitives),
        ),
        patch(
            "core.agents.evaluation_runner._fetch_liquidity",
            new=AsyncMock(return_value=liquidity),
        ),
        patch(
            "core.agents.evaluation_runner._fetch_news_stub",
            new=AsyncMock(return_value=news),
        ),
        patch(
            "core.agents.evaluation_runner._fetch_macro_stub",
            new=AsyncMock(return_value=macro),
        ),
        patch(
            "core.agents.evaluation_runner._call_llm_structured",
            new=AsyncMock(return_value=llm_response),
        ),
        patch(
            "core.agents.evaluation_runner.get_mongo_db",
            new=MagicMock(return_value=_make_mock_db()),
        ),
    ]
    return contextlib.ExitStack(), patches


# ---------------------------------------------------------------------------
# Test 1: Order — Framework().run is called BEFORE _call_llm_structured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_calls_framework_before_llm():
    """Plan 06: order is build ctx → framework.run → LLM call → persist.

    Asserts via call-time stamps that ``Framework().run`` is invoked before
    the LLM completion.
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    call_order: list[str] = []

    real_framework_class = None  # Will be captured

    def _spy_framework_init(self):
        # Trigger the real boot side-effects (strategies registry import etc.)
        # by calling the real __init__ via the captured class.
        real_framework_class.__original_init__(self)

    def _spy_framework_run(self, ctx):
        call_order.append("framework.run")
        return real_framework_class.__original_run__(self, ctx)

    async def _spy_llm(*args, **kwargs):
        call_order.append("llm")
        return _malicious_llm_json(score=42)

    from core.agents.decision_framework.framework import Framework as _RealFramework

    real_framework_class = _RealFramework
    real_framework_class.__original_init__ = _RealFramework.__init__
    real_framework_class.__original_run__ = _RealFramework.run

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(score=42),
    )
    patches.append(
        patch.object(_RealFramework, "run", _spy_framework_run)
    )
    patches.append(
        patch.object(_RealFramework, "__init__", _spy_framework_init)
    )
    # Override LLM patch with the spy (to record order)
    patches[5] = patch(
        "core.agents.evaluation_runner._call_llm_structured", new=_spy_llm
    )

    try:
        with stack:
            for p in patches:
                stack.enter_context(p)
            await run_pre_trade_evaluation(
                journal_id="journal-1", strategy_id=None
            )
    finally:
        # Restore patched-in originals so other tests are not affected.
        if hasattr(real_framework_class, "__original_init__"):
            del real_framework_class.__original_init__
        if hasattr(real_framework_class, "__original_run__"):
            del real_framework_class.__original_run__

    # Order: framework.run came BEFORE the LLM call.
    assert "framework.run" in call_order, (
        "Framework().run must be invoked. call_order=%r" % (call_order,)
    )
    assert "llm" in call_order, "LLM must be invoked. call_order=%r" % (call_order,)
    assert call_order.index("framework.run") < call_order.index("llm"), (
        "Framework().run MUST be invoked before the LLM call. "
        "call_order=%r" % (call_order,)
    )


# ---------------------------------------------------------------------------
# Test 2: CF-2 PROBE — LLM cannot override framework score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_cannot_override_framework_score():
    """**CF-2 — THE LOAD-BEARING TEST.**

    Even if the LLM hallucinates ``score=100``, the runner MUST overwrite via
    ``model_copy(update={"score": framework_result.score, ...})`` BEFORE
    persisting.
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(score=100),
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        result = await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    # The framework computed score from a ctx where Tier-2 returns
    # not_available (HTF/Liquidity/Structure/Momentum/Compression all
    # not_available → score=0 for those categories). Whatever the framework
    # computed, that value MUST win — NOT 100.
    assert result.score != 100, (
        "CRITICAL FAILURE — LLM-supplied score=100 survived. "
        "model_copy(update=...) overwrite MISSING in evaluation_runner. "
        "Phase 47.3 deterministic guarantee BROKEN."
    )


# ---------------------------------------------------------------------------
# Test 3: CF-2 corollary — recommendation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_cannot_override_recommendation():
    """CF-2 corollary: framework's recommendation overwrites LLM's."""
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(recommendation="enter"),
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        result = await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    # With all Tier-2 not_available (score=0), framework recommendation is
    # 'avoid' (band <50). LLM said 'enter'. Framework wins.
    assert result.recommendation == "avoid", (
        "Framework recommendation must overwrite LLM. got=%r"
        % (result.recommendation,)
    )


# ---------------------------------------------------------------------------
# Test 4: CF-2 corollary — confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_cannot_override_confidence():
    """CF-2 corollary: framework's confidence overwrites LLM's."""
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(confidence=0.99),
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        result = await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    # With HIGH-tier capabilities not_available the framework docks
    # confidence; the LLM said 0.99. Framework's confidence_pct/100 wins
    # and is < 0.99.
    assert result.confidence < 0.99, (
        "Framework confidence must overwrite LLM. got=%r" % (result.confidence,)
    )


# ---------------------------------------------------------------------------
# Test 5: CF-2 corollary — category_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_cannot_override_category_results():
    """CF-2 corollary: framework's category_results overwrite LLM's."""
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(),
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        result = await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    # Framework always emits 9 category_results.
    assert len(result.category_results) == 9, (
        "Framework category_results must overwrite LLM's empty list. got len=%d"
        % len(result.category_results)
    )


# ---------------------------------------------------------------------------
# Test 6: Hard reject reasons appended to risks (LLM risks survive too)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_appends_hard_reject_to_risks():
    """Hard reject reasons get appended to risks (LLM-supplied risks survive)."""
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    # With strategy_id="model_2_option_1_short" and Momentum=not_available,
    # the no_displacement hard-reject predicate fires (CF-3 conservative read).
    tier1 = _make_tier1_stub(
        instrument="EURUSD",
        direction="short",
        strategy_id="model_2_option_1_short",
    )
    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(),
        tier1=tier1,
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        result = await run_pre_trade_evaluation(
            journal_id="journal-1",
            strategy_id="model_2_option_1_short",
        )

    # LLM-supplied risk survives + hard_reject reasons appended.
    risks_text = " | ".join(result.risks)
    assert "llm-supplied-risk" in risks_text, (
        "LLM-supplied risks must survive. risks=%r" % (result.risks,)
    )
    assert any(r.startswith("hard_reject:") for r in result.risks), (
        "Hard reject reasons must be appended to risks. risks=%r"
        % (result.risks,)
    )


# ---------------------------------------------------------------------------
# Test 7: Full pipeline e2e with partial_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_e2e_with_partial_context():
    """End-to-end: ctx → framework → LLM → typed PreTradeEvaluation
    with confidence_adjustments populated, partial_context=True."""
    from core.agents.evaluation_runner import run_pre_trade_evaluation
    from fingpt_core.contracts.agents.pre_trade_evaluation import PreTradeEvaluation

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(),
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        result = await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    assert isinstance(result, PreTradeEvaluation)
    # HIGH-tier capabilities not_available → partial_context True.
    assert result.partial_context is True
    # confidence_adjustments populated (one per HIGH/MEDIUM/LOW dock).
    assert len(result.confidence_adjustments) > 0
    # framework_version set to 1 (CF-4: runner explicitly writes 1)
    assert result.framework_version == 1


# ---------------------------------------------------------------------------
# Test 8: Framework Result block injected into LLM messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_narrative_only_prompt_in_messages():
    """The user message MUST include a `## Framework Result` block with the
    structured engine output."""
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    captured_messages: list[list[dict]] = []

    async def _capture_llm(messages, model=None):
        captured_messages.append(messages)
        return _malicious_llm_json()

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(),
    )
    # Replace LLM patch with the capturing spy.
    patches[5] = patch(
        "core.agents.evaluation_runner._call_llm_structured", new=_capture_llm
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    assert captured_messages, "LLM must have been called at least once"
    full_text = json.dumps(captured_messages[0])
    assert "## Framework Result" in full_text or "Framework Result" in full_text, (
        "User message MUST include the Framework Result block. messages=%s"
        % full_text[:500]
    )


# ---------------------------------------------------------------------------
# Test 9: Tier-2 calls parallelized via asyncio.gather
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier2_calls_parallelized_via_asyncio_gather():
    """OQ-3 + Risk 4: Tier-2 fetches must run via asyncio.gather, not sequential.

    Asserts the runner uses ``asyncio.gather`` somewhere in
    ``_build_eval_context`` by patching it and counting the call.
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation
    import asyncio as _asyncio_real

    gather_call_count = {"n": 0}
    real_gather = _asyncio_real.gather

    def _counting_gather(*args, **kwargs):
        gather_call_count["n"] += 1
        return real_gather(*args, **kwargs)

    stack, patches = _patch_runner_dependencies(
        llm_response=_malicious_llm_json(),
    )
    patches.append(
        patch("core.agents.evaluation_runner.asyncio.gather", new=_counting_gather)
    )
    with stack:
        for p in patches:
            stack.enter_context(p)
        await run_pre_trade_evaluation(
            journal_id="journal-1", strategy_id=None
        )

    assert gather_call_count["n"] >= 1, (
        "_build_eval_context must use asyncio.gather to parallelize Tier-2 "
        "fetches. gather call count=%d" % gather_call_count["n"]
    )
