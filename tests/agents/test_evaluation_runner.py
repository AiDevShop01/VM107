"""
Phase 47.1-01 — Wave 0 xfail scaffolding for evaluation_runner.py.

Tests specification for VM107 evaluation runner unit behaviours.
All tests are xfail (Wave 0) until Plan 47.1-02 ships the target module.

Graduated to GREEN by: 47.1-02 / Task 2
Target module: core.agents.evaluation_runner

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

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Test 1: Success path returns PreTradeEvaluation instance
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_success_returns_evaluation():
    """Given mock LLM returns valid JSON for PreTradeEvaluation schema,
    run_pre_trade_evaluation() returns a PreTradeEvaluation instance with
    recommendation populated.

    Graduated to GREEN by: 47.1-02 / Task 2
    CONTEXT-strict-json requirement.
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 2: Two PlainTextResult responses raise EvaluationContractViolation
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_two_plain_text_raises_contract_violation():
    """Mock safe_parse to return PlainTextResult twice.

    Asserts: EvaluationContractViolation raised; exception has envelope_id attribute.

    CONTEXT-fail-fast requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    from core.agents.invocation_exceptions import EvaluationContractViolation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 3: First PlainTextResult triggers retry, second success passes
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_first_plain_text_triggers_retry():
    """Mock LLM/safe_parse: first call returns PlainTextResult, second returns
    valid evaluation.

    Asserts: no exception raised; call count == 2 (retry fired exactly once).

    CONTEXT-fail-fast requirement (retry-once-then-fail).
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 4: Successful run persists envelope with status="success"
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_success_envelope_persisted():
    """After successful run, assert write_envelope called once with
    status="success" and journal_id set.

    CONTEXT-mongo-provenance requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 5: Contract violation persists failure envelope BEFORE raising
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_failure_envelope_on_contract_violation():
    """After 2× PlainTextResult, assert write_envelope called with
    status="failure" BEFORE EvaluationContractViolation is raised.

    This verifies: failure provenance is never lost even on hard errors.
    CONTEXT-mongo-provenance requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    from core.agents.invocation_exceptions import EvaluationContractViolation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 6: History is read from Mongo, NOT received in request body
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_history_read_from_mongo():
    """Assert db["agent_envelopes"].find called with
    {"journal_id": journal_id, "agent_id": "agent_zero"} filter.

    Confirms history is pulled from VM107 Mongo, NOT passed in the request body.
    CONTEXT-evaluation-runner requirement (Critical Finding #3 from RESEARCH).
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 7: Prompt file loads cleanly
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 creates pre_trade_evaluation.md prompt")
def test_prompt_file_loads():
    """Assert pre_trade_evaluation.md exists at
    agents/agent0/prompts/agent.system.main.pre_trade_evaluation.md
    and is non-empty.

    CONTEXT-prompt-file-mode-b requirement.
    Graduated to GREEN by: 47.1-02 / Task 1 (prompt file creation)
    """
    prompt_path = (
        _VM107_ROOT
        / "agents"
        / "agent0"
        / "prompts"
        / "agent.system.main.pre_trade_evaluation.md"
    )
    # When Plan 47.1-02 ships the prompt file, this assertion becomes the real check.
    # For Wave 0 stub: always fail so xfail registers.
    assert prompt_path.exists() and prompt_path.stat().st_size > 0, (
        f"Wave 0 stub — prompt file not yet created at {prompt_path}"
    )
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 8: System fields are injected by runner (not from LLM JSON)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_system_fields_injected():
    """After successful safe_parse, returned evaluation has evaluation_id (UUID),
    trade_id, conversation_id, source_envelope_id, created_at populated by the
    runner via model_copy.

    These fields are NOT in the LLM JSON output (per RESEARCH OQ-5).
    CONTEXT-evaluation-runner requirement.
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")


# ---------------------------------------------------------------------------
# Test 9: evaluation_id is UUID format
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Wave 0 stub — Plan 47.1-02 implements evaluation_runner.py")
def test_evaluation_id_is_uuid_format():
    """Assert that evaluation_id on returned PreTradeEvaluation is a valid UUID.

    Verifies the runner generates a proper UUID, not an arbitrary string.
    CONTEXT-evaluation-runner requirement (parity test per VALIDATION.md count).
    Graduated to GREEN by: 47.1-02 / Task 2
    """
    from core.agents.evaluation_runner import run_pre_trade_evaluation  # noqa: F401
    pytest.fail("Wave 0 stub — implement in Plan 47.1-02")
