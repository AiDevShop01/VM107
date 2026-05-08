"""
Phase 47.1-02 — evaluation_runner.py tests.

Phase 47.3-06 update: the runner now returns ``PreTradeEvaluation`` directly
(no tuple), drops ``context_block`` from kwargs (resolved internally via
Tier-1), and orchestrates Framework().run BEFORE the LLM call. These legacy
47.1 tests are kept for the LLM retry-once-then-fail and envelope-persistence
guarantees that are still in scope.

Test count: 9 (per 47.1-VALIDATION.md Per-Task Verification Map)
  1. test_success_returns_evaluation
  2. test_two_plain_text_raises_contract_violation
  3. test_first_plain_text_triggers_retry
  4. test_success_envelope_persisted
  5. test_failure_envelope_on_contract_violation
  6. test_history_read_from_mongo
  7. test_prompt_file_loads
  8. test_system_fields_injected
  9. test_evaluation_id_is_uuid_format
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _make_tier1():
    return {
        "trade_id": "journal-abc",
        "instrument": "XAUUSD",
        "direction": "long",
        "strategy_id": None,
        "last_evaluation": None,
        "journal_metadata": {"timeframe": "15M"},
    }


def _make_primitives_unav():
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


def _make_liquidity_unav():
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


@contextlib.contextmanager
def _patched_runner_deps():
    """Apply tier-1 / Tier-2 / Tier-3 stubs the legacy tests rely on.

    Lets the LLM mock + db mock remain the only behaviour each test cares about.
    """
    with patch(
        "core.agents.evaluation_runner.build_tier1_context",
        new=AsyncMock(return_value=_make_tier1()),
    ), patch(
        "core.agents.evaluation_runner._fetch_primitives",
        new=AsyncMock(return_value=_make_primitives_unav()),
    ), patch(
        "core.agents.evaluation_runner._fetch_liquidity",
        new=AsyncMock(return_value=_make_liquidity_unav()),
    ), patch(
        "core.agents.evaluation_runner._fetch_news_stub",
        new=AsyncMock(return_value=_make_news_stub()),
    ), patch(
        "core.agents.evaluation_runner._fetch_macro_stub",
        new=AsyncMock(return_value=_make_macro_stub()),
    ):
        yield


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_CANNED_VALID_JSON = json.dumps({
    "recommendation": "enter",
    "confidence": 0.82,
    "score": 74,
    "max_score": 100,
    "direction": "long",
    "instrument": "XAUUSD",
    "check_results": {
        "htf_alignment": "pass",
        "compression_pause": "pass",
        "displacement_candle": "unclear",
        "location_quality": "pass",
        "rr_acceptable": "pass",
    },
    "reasoning_summary": "Strong HTF alignment with clean displacement. Location quality confirmed.",
    "risks": ["Upcoming NFP data could reverse momentum", "Spread widening near session open"],
    "invalidations": ["Price closes below 2618 structure low", "HTF bearish shift confirmed"],
    "next_action": "Enter at 2625 limit, SL 2612, TP 2645. Risk 1%.",
})

_PLAIN_TEXT_RESPONSE = "I cannot produce structured JSON right now, sorry."

_COMMON_KWARGS = dict(
    journal_id="journal-abc",
    conversation_id="journal-abc",
    strategy_id=None,
    user_id="user-1",
)


def _make_mock_db():
    """Return a minimal mock db that satisfies evaluation_runner queries."""
    envelopes_col = MagicMock()
    envelopes_col.find.return_value = iter([])
    envelopes_col.find_one.return_value = None
    envelopes_col.insert_one.return_value = MagicMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: envelopes_col if name == "agent_envelopes" else MagicMock()
    )
    db._col = envelopes_col
    return db


# ---------------------------------------------------------------------------
# Test 1: Success path returns PreTradeEvaluation instance
# ---------------------------------------------------------------------------

def test_success_returns_evaluation():
    """Given mock LLM returns valid JSON for PreTradeEvaluation schema,
    run_pre_trade_evaluation() returns a PreTradeEvaluation instance with
    recommendation populated.

    CONTEXT-strict-json requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation
    from core.contracts.schemas import PreTradeEvaluation

    db = _make_mock_db()
    mock_llm = AsyncMock(return_value=_CANNED_VALID_JSON)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        evaluation = asyncio.run(
            run_pre_trade_evaluation(**_COMMON_KWARGS, db=db)
        )

    assert isinstance(evaluation, PreTradeEvaluation)
    # Phase 47.3: framework owns recommendation; LLM said 'enter' but with
    # all Tier-2 not_available the framework forces 'avoid' (band <50).
    assert evaluation.recommendation == "avoid"
    # Tier-1 echo: instrument is sourced from build_tier1_context, not from
    # the LLM's JSON.
    assert evaluation.instrument == "XAUUSD"


# ---------------------------------------------------------------------------
# Test 2: Two PlainTextResult responses raise EvaluationContractViolation
# ---------------------------------------------------------------------------

def test_two_plain_text_raises_contract_violation():
    """Mock safe_parse to return PlainTextResult twice.

    Asserts: EvaluationContractViolation raised; exception has envelope_id attribute.

    CONTEXT-fail-fast requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation
    from core.agents.invocation_exceptions import EvaluationContractViolation

    db = _make_mock_db()
    # LLM always returns plain text
    mock_llm = AsyncMock(return_value=_PLAIN_TEXT_RESPONSE)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        with pytest.raises(EvaluationContractViolation) as exc_info:
            asyncio.run(run_pre_trade_evaluation(**_COMMON_KWARGS, db=db))

    exc = exc_info.value
    assert hasattr(exc, "envelope_id"), "EvaluationContractViolation must have envelope_id"
    assert exc.envelope_id is not None, "envelope_id must be set after failure envelope written"


# ---------------------------------------------------------------------------
# Test 3: First PlainTextResult triggers retry, second success passes
# ---------------------------------------------------------------------------

def test_first_plain_text_triggers_retry():
    """Mock LLM/safe_parse: first call returns PlainTextResult, second returns
    valid evaluation.

    Asserts: no exception raised; call count == 2 (retry fired exactly once).

    CONTEXT-fail-fast requirement (retry-once-then-fail).
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation
    from core.contracts.schemas import PreTradeEvaluation

    db = _make_mock_db()
    # First call: plain text (causes degraded); second call: valid JSON (success)
    mock_llm = AsyncMock(side_effect=[_PLAIN_TEXT_RESPONSE, _CANNED_VALID_JSON])

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        evaluation = asyncio.run(
            run_pre_trade_evaluation(**_COMMON_KWARGS, db=db)
        )

    assert isinstance(evaluation, PreTradeEvaluation)
    assert mock_llm.call_count == 2, f"Expected 2 LLM calls (retry once), got {mock_llm.call_count}"


# ---------------------------------------------------------------------------
# Test 4: Successful run persists envelope with status="success"
# ---------------------------------------------------------------------------

def test_success_envelope_persisted():
    """After successful run, assert write_envelope called once with
    status="success" and journal_id set.

    CONTEXT-mongo-provenance requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    db = _make_mock_db()
    mock_llm = AsyncMock(return_value=_CANNED_VALID_JSON)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        evaluation = asyncio.run(
            run_pre_trade_evaluation(**_COMMON_KWARGS, db=db)
        )

    # Envelope is written via db["agent_envelopes"].insert_one
    envelopes_col = db["agent_envelopes"]
    assert envelopes_col.insert_one.called, "insert_one must have been called to persist envelope"

    # Check the inserted doc contains status=success and journal_id
    call_args = envelopes_col.insert_one.call_args_list
    assert len(call_args) >= 1, "At least one envelope must be persisted"
    # Find the success envelope (last insert for a clean successful run)
    success_docs = [args[0][0] for args in call_args if args[0][0].get("status") == "success"]
    assert len(success_docs) >= 1, "At least one success envelope must be persisted"
    assert success_docs[0]["journal_id"] == "journal-abc"


# ---------------------------------------------------------------------------
# Test 5: Contract violation persists failure envelope BEFORE raising
# ---------------------------------------------------------------------------

def test_failure_envelope_on_contract_violation():
    """After 2× PlainTextResult, assert write_envelope called with
    status="failure" BEFORE EvaluationContractViolation is raised.

    This verifies: failure provenance is never lost even on hard errors.
    CONTEXT-mongo-provenance requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation
    from core.agents.invocation_exceptions import EvaluationContractViolation

    db = _make_mock_db()
    mock_llm = AsyncMock(return_value=_PLAIN_TEXT_RESPONSE)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        with pytest.raises(EvaluationContractViolation):
            asyncio.run(run_pre_trade_evaluation(**_COMMON_KWARGS, db=db))

    envelopes_col = db["agent_envelopes"]
    call_args = envelopes_col.insert_one.call_args_list
    failure_docs = [args[0][0] for args in call_args if args[0][0].get("status") == "failure"]
    assert len(failure_docs) >= 1, "At least one failure envelope must be persisted before raise"


# ---------------------------------------------------------------------------
# Test 6: History is read from Mongo, NOT received in request body
# ---------------------------------------------------------------------------

def test_history_read_from_mongo():
    """Assert db["agent_envelopes"].find called with
    {"journal_id": journal_id, "agent_id": "agent_zero"} filter.

    Confirms history is pulled from VM107 Mongo, NOT passed in the request body.
    CONTEXT-evaluation-runner requirement (Critical Finding #3 from RESEARCH).
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    db = _make_mock_db()
    mock_llm = AsyncMock(return_value=_CANNED_VALID_JSON)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        asyncio.run(run_pre_trade_evaluation(**_COMMON_KWARGS, db=db))

    envelopes_col = db["agent_envelopes"]
    envelopes_col.find.assert_called_once()
    call_kwargs = envelopes_col.find.call_args
    # The first positional arg is the filter dict
    filter_arg = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("filter", {})
    assert filter_arg.get("journal_id") == "journal-abc"
    assert filter_arg.get("agent_id") == "agent_zero"


# ---------------------------------------------------------------------------
# Test 7: Prompt file loads cleanly
# ---------------------------------------------------------------------------

def test_prompt_file_loads():
    """Assert pre_trade_evaluation.md exists at
    agents/agent0/prompts/agent.system.main.pre_trade_evaluation.md
    and is non-empty.

    CONTEXT-prompt-file-mode-b requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    prompt_path = (
        _VM107_ROOT
        / "agents"
        / "agent0"
        / "prompts"
        / "agent.system.main.pre_trade_evaluation.md"
    )
    assert prompt_path.exists(), f"Prompt file not found at {prompt_path}"
    assert prompt_path.stat().st_size > 0, "Prompt file must be non-empty"
    content = prompt_path.read_text(encoding="utf-8")
    assert "{schema_json}" in content, "Prompt file must contain {schema_json} placeholder"


# ---------------------------------------------------------------------------
# Test 8: System fields are injected by runner (not from LLM JSON)
# ---------------------------------------------------------------------------

def test_system_fields_injected():
    """After successful safe_parse, returned evaluation has evaluation_id (UUID),
    trade_id, conversation_id, source_envelope_id, created_at populated by the
    runner via model_copy.

    These fields are NOT in the LLM JSON output (per RESEARCH OQ-5).
    CONTEXT-evaluation-runner requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    db = _make_mock_db()
    mock_llm = AsyncMock(return_value=_CANNED_VALID_JSON)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        evaluation = asyncio.run(
            run_pre_trade_evaluation(**_COMMON_KWARGS, db=db)
        )

    assert evaluation.trade_id == "journal-abc", f"trade_id must be journal_id, got {evaluation.trade_id!r}"
    assert evaluation.conversation_id == "journal-abc", f"conversation_id must equal journal_id, got {evaluation.conversation_id!r}"
    assert evaluation.evaluation_id != "", "evaluation_id must be populated by runner"
    assert evaluation.created_at is not None, "created_at must be set by runner"
    # source_envelope_id is "" when no prior envelope exists in Mongo (find_one returns None)
    assert isinstance(evaluation.source_envelope_id, str)


# ---------------------------------------------------------------------------
# Test 9: evaluation_id is UUID format
# ---------------------------------------------------------------------------

def test_evaluation_id_is_uuid_format():
    """Assert that evaluation_id on returned PreTradeEvaluation is a valid UUID.

    Verifies the runner generates a proper UUID, not an arbitrary string.
    CONTEXT-evaluation-runner requirement (parity test per VALIDATION.md count).
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation

    db = _make_mock_db()
    mock_llm = AsyncMock(return_value=_CANNED_VALID_JSON)

    with _patched_runner_deps(), patch(
        "core.agents.evaluation_runner._call_llm_structured", new=mock_llm
    ):
        evaluation = asyncio.run(
            run_pre_trade_evaluation(**_COMMON_KWARGS, db=db)
        )

    # Validate UUID format — uuid.UUID() raises ValueError if invalid
    try:
        parsed = uuid.UUID(evaluation.evaluation_id)
    except ValueError as e:
        pytest.fail(f"evaluation_id is not a valid UUID: {evaluation.evaluation_id!r} — {e}")

    assert str(parsed) == evaluation.evaluation_id, "evaluation_id must be canonical UUID string"
