"""Phase 47.3 — evaluation_runner refactor tests.

CRITICAL: test_llm_cannot_override_framework_score is THE Critical-Finding-2
probe. If it fails (LLM-supplied score wins), Phase 47.3's deterministic
guarantee is broken in one missing model_copy line.

Wave 0 — graduates in Plan 06 (runner refactor shipped).
"""
import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.xfail(
    reason="Phase 47.3 — runner refactor not yet shipped (Plan 06)",
    strict=False,
)


@pytest.mark.asyncio
async def test_runner_calls_framework_before_llm():
    """Plan 06: order is build ctx → framework.run → LLM call → persist."""
    raise NotImplementedError("Plan 06 ships call-order test")


@pytest.mark.asyncio
async def test_llm_cannot_override_framework_score():
    """**CF-2 — THE LOAD-BEARING TEST.**

    Even if the LLM hallucinates score=100, the runner MUST overwrite via
    model_copy(update={"score": framework_result.score, ...}) before persist.
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    # Mock LLM to return a wildly different score (100) than framework would compute.
    malicious_llm_payload = {
        "score": 100, "max_score": 100, "recommendation": "enter",
        "confidence": 0.99, "category_results": [],
        "reasoning_summary": "Looks great!", "risks": [], "invalidations": [],
        "next_action": "enter", "instrument": "X", "direction": "long",
        "evaluation_id": "x", "trade_id": "x", "conversation_id": "x",
        "source_envelope_id": "x",
    }

    with patch(
        "core.agents.evaluation_runner._call_llm_structured",
        new=AsyncMock(
            return_value=type(
                "R", (), {"data": type("D", (), malicious_llm_payload)()}
            )()
        ),
    ):
        result = await run_pre_trade_evaluation(journal_id="test", strategy_id=None)

    # The framework computes score from real ctx (which is empty/minimal here).
    # Whatever the framework computed, that value MUST win — NOT 100.
    assert result.score != 100, (
        "CRITICAL FAILURE — LLM-supplied score survived. "
        "model_copy(update=...) overwrite MISSING in evaluation_runner. "
        "Phase 47.3 deterministic guarantee BROKEN."
    )


@pytest.mark.asyncio
async def test_llm_cannot_override_recommendation():
    """CF-2 corollary: framework's recommendation overwrites LLM's."""
    raise NotImplementedError("Plan 06 ships")


@pytest.mark.asyncio
async def test_llm_cannot_override_confidence():
    """CF-2 corollary: framework's confidence overwrites LLM's."""
    raise NotImplementedError("Plan 06 ships")


@pytest.mark.asyncio
async def test_llm_cannot_override_category_results():
    """CF-2 corollary: framework's category_results overwrite LLM's."""
    raise NotImplementedError("Plan 06 ships")


@pytest.mark.asyncio
async def test_runner_appends_hard_reject_to_risks():
    """Hard reject reasons get appended to risks (LLM-supplied risks survive)."""
    raise NotImplementedError("Plan 06 ships")


@pytest.mark.asyncio
async def test_full_pipeline_e2e_with_partial_context():
    """End-to-end: ctx → framework → LLM → typed PreTradeEvaluation
    with confidence_adjustments populated."""
    raise NotImplementedError("Plan 06 ships e2e test")


@pytest.mark.asyncio
async def test_narrative_only_prompt_in_messages():
    """The user message MUST include a `## Framework Result` block with the
    structured engine output."""
    raise NotImplementedError("Plan 06 ships")


@pytest.mark.asyncio
async def test_tier2_calls_parallelized_via_asyncio_gather():
    """OQ-3 + Risk 4: 5 Tier-2 fetches must run via asyncio.gather, not sequential."""
    raise NotImplementedError("Plan 06 ships parallelization test")
