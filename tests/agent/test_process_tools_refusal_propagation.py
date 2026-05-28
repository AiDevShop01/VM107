"""Phase 70.5 Plan 04 — TDD: process_tools() refused/failure envelope propagation.

Ensures that refused and failure envelopes surface distinctly to the LLM:
  - Refused: Response.message contains outcome="refused", refusal_reason, envelope_id.
  - Failure: Response.message contains outcome="failure", failure_modes, envelope_id.
  - Both: break_loop is False (refusals/failures are recoverable — LLM may pick another tool).

Tests (RED phase — all fail until agent.py is refactored):
    1. Refused envelope: outcome, refusal_reason, envelope_id in message; break_loop False.
    2. Failure envelope: outcome, failure_modes, envelope_id in message; break_loop False.
    3. envelope_id in both outcomes (cross-system trace correlation invariant).
    4. Refused envelope does NOT break loop (break_loop=False).
    5. Failure envelope does NOT break loop (break_loop=False).
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Shared helpers — same pattern as test_process_tools_dispatch.py
# ---------------------------------------------------------------------------

def _make_tool_msg(tool_name: str, tool_args: dict | None = None) -> str:
    return json.dumps({"tool_name": tool_name, "tool_args": tool_args or {}})


def _make_refused_envelope(
    tool_name: str = "my_tool",
    refusal_reason: str = "capability_unavailable:stub",
    envelope_id: uuid.UUID | None = None,
) -> MagicMock:
    env = MagicMock()
    env.envelope_id = envelope_id or uuid.uuid4()
    env.tool_name = tool_name
    env.tool_version = "1.0"
    env.outcome_class = "refused"
    env.success = False
    env.refusal_reason = refusal_reason
    env.confidence = None
    env.freshness_seconds = None
    env.citations = ()
    env.assumptions = ()
    env.failure_modes = ()
    env.payload = MagicMock()
    env.payload.model_dump = MagicMock(return_value={})
    return env


def _make_failure_envelope(
    tool_name: str = "my_tool",
    envelope_id: uuid.UUID | None = None,
) -> MagicMock:
    env = MagicMock()
    env.envelope_id = envelope_id or uuid.uuid4()
    env.tool_name = tool_name
    env.tool_version = "1.0"
    env.outcome_class = "failure"
    env.success = False
    env.refusal_reason = None
    env.confidence = None
    env.freshness_seconds = None
    env.citations = ()
    env.assumptions = ()
    fm = MagicMock()
    fm.model_dump = MagicMock(return_value={"code": "INSUFFICIENT_CONTEXT", "detail": "boom"})
    env.failure_modes = (fm,)
    env.payload = MagicMock()
    env.payload.model_dump = MagicMock(return_value={})
    return env


def _make_agent_stub(agent_name: str = "A0") -> MagicMock:
    stub = MagicMock(name="AgentStub")
    stub.agent_name = agent_name
    loop_data = MagicMock(name="LoopData")
    loop_data.current_tool = None
    # _current_trace_id starts None so that process_tools generates a fresh UUID
    loop_data._current_trace_id = None
    stub.loop_data = loop_data
    stub.context = MagicMock(name="AgentContext")
    stub.context.id = "test-conversation"
    stub.context.log = MagicMock()
    stub.context.paused = False
    stub.handle_intervention = AsyncMock()
    stub.validate_tool_request = AsyncMock()
    stub.hist_add_warning = MagicMock(return_value=MagicMock(id="w1"))
    stub.hist_add_tool_result = MagicMock()
    stub.read_prompt = MagicMock(return_value="misformat warning")
    # Bind the real _envelope_to_response so process_tools produces real JSON messages.
    stub._envelope_to_response = lambda env: _ENVELOPE_TO_RESPONSE_FN(stub, env)
    return stub


def _make_tool_stub(name: str = "my_tool") -> MagicMock:
    from helpers.tool import Response
    tool = MagicMock(name="ToolStub")
    tool.name = name
    tool.progress = ""
    tool.before_execution = AsyncMock()
    tool.after_execution = AsyncMock()
    tool.set_progress = AsyncMock()
    tool.execute = AsyncMock(return_value=Response(message="direct_result", break_loop=False))
    return tool


import agent as _agent_module  # noqa: E402

_PROCESS_TOOLS_FN = getattr(
    _agent_module.Agent.process_tools,
    "__wrapped__",
    _agent_module.Agent.process_tools,
)

_ENVELOPE_TO_RESPONSE_FN = _agent_module.Agent._envelope_to_response


# ---------------------------------------------------------------------------
# Helper to capture response passed to tool_execute_after extension hook
# ---------------------------------------------------------------------------

def _run_with_envelope(
    envelope: MagicMock, tool_name: str = "my_tool"
) -> tuple[MagicMock, list]:
    """Run process_tools with the given envelope; return (agent_stub, captured_responses)."""
    msg = _make_tool_msg(tool_name, {})
    agent_stub = _make_agent_stub()
    tool_stub = _make_tool_stub(name=tool_name)

    mock_summary = MagicMock(name="CapabilitySummary")
    mock_registry = MagicMock(name="CapabilityRegistry")
    mock_registry.lookup.return_value = mock_summary

    captured_responses: list = []

    async def _capture_after(hook_name, agent, **kwargs):
        if hook_name == "tool_execute_after" and "response" in kwargs:
            captured_responses.append(kwargs["response"])

    dispatch_mock = AsyncMock(return_value=envelope)

    with patch("agent.CapabilityRegistry") as mock_reg_cls, \
         patch("agent.dispatch_tool", dispatch_mock), \
         patch("helpers.extension.call_extensions_async", side_effect=_capture_after):

        mock_reg_cls.get.return_value = mock_registry
        agent_stub.get_tool = MagicMock(return_value=tool_stub)

        with patch.dict(sys.modules, {"helpers.mcp_handler": None}):
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))

    return agent_stub, captured_responses


# ---------------------------------------------------------------------------
# Test 1: Refused envelope — outcome, refusal_reason, envelope_id in message
# ---------------------------------------------------------------------------

def test_refused_envelope_message_contains_refusal_reason():
    """Refused envelopes surface refusal_reason and outcome='refused' to the LLM.

    The converted Response.message must contain:
        - "outcome": "refused"
        - "refusal_reason": "capability_unavailable:stub"
        - "envelope_id": str(envelope.envelope_id)
    """
    eid = uuid.uuid4()
    envelope = _make_refused_envelope(
        refusal_reason="capability_unavailable:stub",
        envelope_id=eid,
    )

    _, captured = _run_with_envelope(envelope)
    assert captured, "No response captured from tool_execute_after"
    resp = captured[0]

    parsed = json.loads(resp.message)
    assert parsed["outcome"] == "refused", f"Expected outcome=refused, got {parsed.get('outcome')!r}"
    assert parsed["refusal_reason"] == "capability_unavailable:stub", (
        f"Expected refusal_reason='capability_unavailable:stub', got {parsed.get('refusal_reason')!r}"
    )
    assert parsed["envelope_id"] == str(eid), (
        f"envelope_id mismatch: expected {eid!s}, got {parsed.get('envelope_id')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: Failure envelope — outcome, failure_modes, envelope_id in message
# ---------------------------------------------------------------------------

def test_failure_envelope_message_contains_failure_modes():
    """Failure envelopes surface failure_modes and outcome='failure' to the LLM.

    The converted Response.message must contain:
        - "outcome": "failure"
        - "failure_modes": non-empty list
        - "envelope_id": str(envelope.envelope_id)
    """
    eid = uuid.uuid4()
    envelope = _make_failure_envelope(envelope_id=eid)

    _, captured = _run_with_envelope(envelope)
    assert captured, "No response captured from tool_execute_after"
    resp = captured[0]

    parsed = json.loads(resp.message)
    assert parsed["outcome"] == "failure", f"Expected outcome=failure, got {parsed.get('outcome')!r}"
    assert "failure_modes" in parsed, "failure_modes key missing from failure envelope message"
    assert len(parsed["failure_modes"]) > 0, "failure_modes list is empty"
    assert parsed["envelope_id"] == str(eid), (
        f"envelope_id mismatch: expected {eid!s}, got {parsed.get('envelope_id')!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: envelope_id present in BOTH outcomes
# ---------------------------------------------------------------------------

def test_envelope_id_present_in_all_outcomes():
    """envelope_id is always in Response.message regardless of outcome.

    Cross-system trace correlation requires envelope_id on every outcome path.
    """
    refused_eid = uuid.uuid4()
    failure_eid = uuid.uuid4()

    refused_env = _make_refused_envelope(envelope_id=refused_eid)
    failure_env = _make_failure_envelope(envelope_id=failure_eid)

    _, refused_captured = _run_with_envelope(refused_env, tool_name="my_tool")
    _, failure_captured = _run_with_envelope(failure_env, tool_name="my_tool")

    assert refused_captured
    assert failure_captured

    refused_parsed = json.loads(refused_captured[0].message)
    failure_parsed = json.loads(failure_captured[0].message)

    assert "envelope_id" in refused_parsed, "envelope_id missing from refused envelope message"
    assert "envelope_id" in failure_parsed, "envelope_id missing from failure envelope message"

    assert refused_parsed["envelope_id"] == str(refused_eid)
    assert failure_parsed["envelope_id"] == str(failure_eid)


# ---------------------------------------------------------------------------
# Test 4: Refused envelope does NOT break loop
# ---------------------------------------------------------------------------

def test_refused_envelope_does_not_break_loop():
    """Refused envelopes produce Response with break_loop=False.

    Refusals are recoverable — the LLM may pick a different tool.
    break_loop=True would halt the agent loop, which must NOT happen on refusal.
    """
    envelope = _make_refused_envelope(refusal_reason="capability_unavailable:stub")
    _, captured = _run_with_envelope(envelope)

    assert captured, "No response captured"
    resp = captured[0]
    assert resp.break_loop is False, (
        f"Expected break_loop=False for refused envelope, got {resp.break_loop!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: Failure envelope does NOT break loop
# ---------------------------------------------------------------------------

def test_failure_envelope_does_not_break_loop():
    """Failure envelopes produce Response with break_loop=False.

    Failures are surfaced to the LLM as error context — the agent loop continues.
    break_loop=True would halt the agent loop, which must NOT happen on failure.
    """
    envelope = _make_failure_envelope()
    _, captured = _run_with_envelope(envelope)

    assert captured, "No response captured"
    resp = captured[0]
    assert resp.break_loop is False, (
        f"Expected break_loop=False for failure envelope, got {resp.break_loop!r}"
    )
