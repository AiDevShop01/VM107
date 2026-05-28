"""Phase 70.5 Plan 04 — TDD: process_tools() dispatch routing tests.

Decision 16: process_tools() routes registered-tool calls through dispatch_tool().
Decision 19: Top-level InvocationContext constructed per-request (depth=0).

Tests (RED phase — all fail until agent.py is refactored):
    1. Registered tool: dispatch_tool is awaited; tool.execute() is NOT called.
    2. Success envelope → Response serialization preserves envelope_id, outcome, confidence.
    3. Unregistered tool: MCP/tool.execute() fallback path taken; dispatch_tool NOT called.
    4. Trace_id stability: two process_tools calls in same turn share trace_id.
    5. InvocationContext: depth=0, parent_envelope_id=None on top-level context.

Test strategy:
    - Patch CapabilityRegistry.get().lookup() to simulate registered/unregistered tools.
    - Patch dispatch_tool to return a synthetic envelope (avoid resolver wiring).
    - Build a minimal Agent-like stub — do NOT instantiate the real Agent class
      (heavy LLM + Docker dependencies). Extract process_tools from Agent class
      and bind it to a MagicMock stub (same pattern as test_validate_tool_request_aliases).
    - JSON-encode a tool-request message matching process_tools() parsing logic.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _make_tool_msg(tool_name: str, tool_args: dict | None = None) -> str:
    """Return a message string that process_tools() will parse as a tool request."""
    return json.dumps({
        "tool_name": tool_name,
        "tool_args": tool_args or {},
    })


def _make_success_envelope(
    tool_name: str = "test_tool",
    confidence: float = 0.85,
    envelope_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a mock ToolResultEnvelope with success outcome."""
    env = MagicMock()
    env.envelope_id = envelope_id or uuid.uuid4()
    env.tool_name = tool_name
    env.tool_version = "1.0"
    env.outcome_class = "success"
    env.success = True
    env.refusal_reason = None
    env.confidence = confidence
    env.freshness_seconds = None
    env.citations = ()
    env.assumptions = ()
    env.failure_modes = ()
    # payload with model_dump
    env.payload = MagicMock()
    env.payload.model_dump = MagicMock(return_value={"data": "test_result"})
    return env


def _make_refused_envelope(
    tool_name: str = "test_tool",
    refusal_reason: str = "capability_unavailable:stub",
    envelope_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a mock ToolResultEnvelope with refused outcome."""
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
    tool_name: str = "test_tool",
    envelope_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a mock ToolResultEnvelope with failure outcome."""
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


# ---------------------------------------------------------------------------
# Import the real process_tools method body (extract from Agent class).
# conftest.py ensures ``agent`` module is already loaded.
# ---------------------------------------------------------------------------
import agent as _agent_module  # noqa: E402  (real module guaranteed by conftest.py)

_PROCESS_TOOLS_FN = getattr(
    _agent_module.Agent.process_tools,
    "__wrapped__",
    _agent_module.Agent.process_tools,
)

# Extract _envelope_to_response — it's a plain method, not extensible-wrapped.
_ENVELOPE_TO_RESPONSE_FN = _agent_module.Agent._envelope_to_response


def _make_agent_stub(agent_name: str = "A0") -> MagicMock:
    """Build a minimal agent stub that satisfies process_tools() internals."""
    stub = MagicMock(name="AgentStub")
    stub.agent_name = agent_name

    # loop_data needs: current_tool setter, hist_add_warning, hist_add_tool_result
    loop_data = MagicMock(name="LoopData")
    loop_data.current_tool = None
    # _current_trace_id starts None so that process_tools generates a fresh UUID
    loop_data._current_trace_id = None
    stub.loop_data = loop_data

    # context.id for conversation_id
    stub.context = MagicMock(name="AgentContext")
    stub.context.id = "test-conversation-id"
    stub.context.log = MagicMock()
    stub.context.paused = False

    # handle_intervention is a no-op async
    stub.handle_intervention = AsyncMock()

    # validate_tool_request passes through
    stub.validate_tool_request = AsyncMock()

    # hist_add_warning, hist_add_tool_result
    stub.hist_add_warning = MagicMock(return_value=MagicMock(id="w1"))
    stub.hist_add_tool_result = MagicMock()

    # read_prompt
    stub.read_prompt = MagicMock(return_value="misformat warning")

    # Bind the real _envelope_to_response so process_tools produces real JSON messages.
    # Using a lambda that calls the unbound method with the stub as self.
    stub._envelope_to_response = lambda env: _ENVELOPE_TO_RESPONSE_FN(stub, env)

    return stub


def _make_tool_stub(
    name: str = "test_tool",
    break_loop: bool = False,
    execute_return_message: str = "direct_result",
) -> MagicMock:
    """Build a minimal tool stub that satisfies the tool lifecycle hooks."""
    from helpers.tool import Response

    tool = MagicMock(name="ToolStub")
    tool.name = name
    tool.progress = ""
    tool.before_execution = AsyncMock()
    tool.after_execution = AsyncMock()
    tool.set_progress = AsyncMock()
    tool.execute = AsyncMock(
        return_value=Response(message=execute_return_message, break_loop=break_loop)
    )
    return tool


# ---------------------------------------------------------------------------
# Test 1: Registered tool → dispatch_tool called; tool.execute NOT called
# ---------------------------------------------------------------------------

def test_registered_tool_routes_through_dispatch_tool():
    """Registered tools bypass tool.execute() and route through dispatch_tool().

    Decision 16 invariant: when CapabilityRegistry.get().lookup(tool_name) is
    not None, dispatch_tool() is awaited exactly once with the correct tool_id
    and kwargs. The existing tool.execute() path must NOT be called.
    """
    from helpers.tool import Response

    tool_name = "my_registered_tool"
    tool_args = {"query": "test query"}
    msg = _make_tool_msg(tool_name, tool_args)

    success_env = _make_success_envelope(tool_name=tool_name, confidence=0.85)
    tool_stub = _make_tool_stub(name=tool_name)
    agent_stub = _make_agent_stub()

    # Simulate registry lookup finding a registered tool
    mock_summary = MagicMock(name="CapabilitySummary")
    mock_registry = MagicMock(name="CapabilityRegistry")
    mock_registry.lookup.return_value = mock_summary

    dispatch_mock = AsyncMock(return_value=success_env)

    with patch("agent.CapabilityRegistry") as mock_reg_cls, \
         patch("agent.dispatch_tool", dispatch_mock), \
         patch("helpers.extension.call_extensions_async", new_callable=AsyncMock):

        mock_reg_cls.get.return_value = mock_registry

        # Patch get_tool to return our stub (fallback path)
        agent_stub.get_tool = MagicMock(return_value=tool_stub)

        # MCP lookup returns nothing (no MCP tool)
        with patch.dict(sys.modules, {"helpers.mcp_handler": None}):
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))

    # dispatch_tool was awaited with the registered tool name
    dispatch_mock.assert_awaited_once()
    call_args = dispatch_mock.call_args
    assert call_args[0][0] == tool_name, f"Expected tool_id={tool_name!r}, got {call_args[0][0]!r}"
    assert call_args[0][1] == tool_args, f"Expected kwargs={tool_args!r}, got {call_args[0][1]!r}"

    # tool.execute was NOT called (dispatch_tool is the only invocation surface)
    tool_stub.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 2: Success envelope → Response serialization
# ---------------------------------------------------------------------------

def test_success_envelope_serialized_to_response_message():
    """A success envelope from dispatch_tool is serialized into Response.message.

    The serialized message must contain: envelope_id, outcome=success, confidence=0.85.
    """
    tool_name = "my_registered_tool"
    eid = uuid.uuid4()
    success_env = _make_success_envelope(
        tool_name=tool_name, confidence=0.85, envelope_id=eid
    )
    msg = _make_tool_msg(tool_name, {})

    agent_stub = _make_agent_stub()
    tool_stub = _make_tool_stub(name=tool_name)

    mock_summary = MagicMock(name="CapabilitySummary")
    mock_registry = MagicMock(name="CapabilityRegistry")
    mock_registry.lookup.return_value = mock_summary

    captured_response: list = []

    async def _capture_after(hook_name, agent, **kwargs):
        if hook_name == "tool_execute_after" and "response" in kwargs:
            captured_response.append(kwargs["response"])
        # Return None to satisfy the awaitable contract

    dispatch_mock = AsyncMock(return_value=success_env)
    ext_mock = AsyncMock(side_effect=_capture_after)

    with patch("agent.CapabilityRegistry") as mock_reg_cls, \
         patch("agent.dispatch_tool", dispatch_mock), \
         patch("helpers.extension.call_extensions_async", ext_mock):

        mock_reg_cls.get.return_value = mock_registry
        agent_stub.get_tool = MagicMock(return_value=tool_stub)

        with patch.dict(sys.modules, {"helpers.mcp_handler": None}):
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))

    # Must have captured a response via tool_execute_after hook
    assert captured_response, "tool_execute_after was not called with a response"
    resp = captured_response[0]

    parsed = json.loads(resp.message)
    assert parsed["outcome"] == "success", f"Expected outcome=success, got {parsed.get('outcome')!r}"
    assert str(eid) == parsed["envelope_id"], f"envelope_id mismatch: {parsed.get('envelope_id')!r}"
    assert abs(parsed["confidence"] - 0.85) < 1e-6, f"confidence mismatch: {parsed.get('confidence')}"


# ---------------------------------------------------------------------------
# Test 3: Unregistered tool → MCP/tool.execute fallback; dispatch_tool NOT called
# ---------------------------------------------------------------------------

def test_unregistered_tool_takes_execute_fallback():
    """Unregistered tools continue through the existing tool.execute() path.

    When CapabilityRegistry.get().lookup(tool_name) returns None, the MCP/local
    tool.execute() path must be taken. dispatch_tool must NOT be called.
    """
    tool_name = "unknown_mcp_tool"
    msg = _make_tool_msg(tool_name, {"arg": "value"})

    tool_stub = _make_tool_stub(name=tool_name)
    agent_stub = _make_agent_stub()

    mock_registry = MagicMock(name="CapabilityRegistry")
    mock_registry.lookup.return_value = None  # NOT registered

    dispatch_mock = AsyncMock()

    with patch("agent.CapabilityRegistry") as mock_reg_cls, \
         patch("agent.dispatch_tool", dispatch_mock), \
         patch("helpers.extension.call_extensions_async", new_callable=AsyncMock):

        mock_reg_cls.get.return_value = mock_registry
        agent_stub.get_tool = MagicMock(return_value=tool_stub)

        with patch.dict(sys.modules, {"helpers.mcp_handler": None}):
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))

    # dispatch_tool must NOT be called for unregistered tools
    dispatch_mock.assert_not_awaited()

    # tool.execute() must have been called (fallback path)
    tool_stub.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4: Trace_id stability across same-turn calls
# ---------------------------------------------------------------------------

def test_trace_id_stable_across_same_turn_calls():
    """Two process_tools() calls in the same agent turn share the same trace_id.

    The trace_id is set on first dispatch and reused on subsequent calls within
    the same turn (same loop_data). This ensures correlation across multi-tool
    agent turns.
    """
    tool_name = "my_registered_tool"
    msg = _make_tool_msg(tool_name, {})

    mock_summary = MagicMock(name="CapabilitySummary")
    mock_registry = MagicMock(name="CapabilityRegistry")
    mock_registry.lookup.return_value = mock_summary

    tool_stub = _make_tool_stub(name=tool_name)
    agent_stub = _make_agent_stub()

    success_env = _make_success_envelope(tool_name=tool_name)
    captured_ctxs: list = []

    async def _capture_dispatch(tool_id, kwargs, ctx):
        captured_ctxs.append(ctx)
        return success_env

    with patch("agent.CapabilityRegistry") as mock_reg_cls, \
         patch("agent.dispatch_tool", side_effect=_capture_dispatch), \
         patch("helpers.extension.call_extensions_async", new_callable=AsyncMock):

        mock_reg_cls.get.return_value = mock_registry
        agent_stub.get_tool = MagicMock(return_value=tool_stub)

        with patch.dict(sys.modules, {"helpers.mcp_handler": None}):
            # Call process_tools twice in the same "turn" (same loop_data)
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))

    assert len(captured_ctxs) == 2, f"Expected 2 dispatch calls, got {len(captured_ctxs)}"

    first_trace_id = captured_ctxs[0].trace_id
    second_trace_id = captured_ctxs[1].trace_id
    assert first_trace_id == second_trace_id, (
        f"trace_id changed between same-turn calls: {first_trace_id} != {second_trace_id}"
    )


# ---------------------------------------------------------------------------
# Test 5: InvocationContext shape — top-level context is depth=0
# ---------------------------------------------------------------------------

def test_invocation_context_top_level_shape():
    """Top-level InvocationContext has depth=0 and parent_envelope_id=None.

    Decision 19: the agent constructs a top-level context per process_tools()
    call with execution_depth=0 and parent_envelope_id=None.
    """
    tool_name = "my_registered_tool"
    msg = _make_tool_msg(tool_name, {})

    mock_summary = MagicMock(name="CapabilitySummary")
    mock_registry = MagicMock(name="CapabilityRegistry")
    mock_registry.lookup.return_value = mock_summary

    tool_stub = _make_tool_stub(name=tool_name)
    agent_stub = _make_agent_stub(agent_name="A0")
    agent_stub.context.id = "conv-abc-123"

    success_env = _make_success_envelope(tool_name=tool_name)
    captured_ctxs: list = []

    async def _capture_dispatch(tool_id, kwargs, ctx):
        captured_ctxs.append(ctx)
        return success_env

    with patch("agent.CapabilityRegistry") as mock_reg_cls, \
         patch("agent.dispatch_tool", side_effect=_capture_dispatch), \
         patch("helpers.extension.call_extensions_async", new_callable=AsyncMock):

        mock_reg_cls.get.return_value = mock_registry
        agent_stub.get_tool = MagicMock(return_value=tool_stub)

        with patch.dict(sys.modules, {"helpers.mcp_handler": None}):
            asyncio.run(_PROCESS_TOOLS_FN(agent_stub, msg))

    assert len(captured_ctxs) == 1
    ctx = captured_ctxs[0]

    assert ctx.execution_depth == 0, f"Expected depth=0, got {ctx.execution_depth}"
    assert ctx.parent_envelope_id is None, (
        f"Expected parent_envelope_id=None, got {ctx.parent_envelope_id}"
    )
    assert ctx.agent_id == "A0", f"Expected agent_id='A0', got {ctx.agent_id!r}"
    assert ctx.conversation_id == "conv-abc-123", (
        f"Expected conversation_id='conv-abc-123', got {ctx.conversation_id!r}"
    )
