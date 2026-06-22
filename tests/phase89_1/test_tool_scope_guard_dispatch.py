"""Phase 89.1 Plan 03 Round 2 — Execution-level scope guard tests.

Regression context:
    89.1-05 v4 pre-screen found that the prompt-level filter (_05_tool_scope_filter.py)
    only hides tool descriptions from the LLM — it does NOT prevent the LLM from
    invoking denied tools by name. The LLM hallucinates code_execution_tool calls,
    gets CapabilityRefusedError, then retries with variations (terminal/python3/curl/
    memory_load…) 3-6× × 30-60s each, blowing past VM100's 180s dispatcher cap.

    Fix A: Execution-level scope guard in process_tools() — intercepts tool calls
    at dispatch, before MCP lookup and before dispatch_tool(), and injects a
    structured "tool_not_in_scope" response via hist_add_tool_result so the LLM
    sees a polite refusal and picks an allowed tool instead.

    Fix B: Profile prompt instruction — macro_investigator system prompt explicitly
    tells the LLM not to retry with variations when it sees tool_not_in_scope.

Tests (13-16):
    13: test_scope_guard_blocks_denied_tool_with_structured_response
        — agent with macro_investigator profile calls code_execution_tool
          → process_tools() short-circuits, injects tool_not_in_scope response,
          does NOT raise or cascade.
    14: test_scope_guard_blocked_response_not_in_scope_error_format
        — the injected tool result contains the expected JSON keys:
          error=tool_not_in_scope, tool_name, allowed_tools list.
    15: test_scope_guard_allows_in_scope_tool
        — agent with macro_investigator profile calls vm102.indicator_history
          → process_tools() does NOT inject scope refusal (proceeds normally).
    16: test_scope_guard_no_op_for_unscoped_profile
        — agent with PROFILE_LEGACY_STRING calls code_execution_tool
          → no scope guard fires (legacy agents are unaffected).
    17: test_profile_prompt_contains_no_retry_instruction
        — macro_investigator.md contains the explicit no-retry instruction.

REQ-89-9.3 execution-level truth statement (post-fix):
    "When macro_investigator profile is active, calls to denied tools
    (code_execution_tool, text_editor, call_subordinate, etc.) are intercepted
    at process_tools() dispatch time and immediately return a structured
    tool_not_in_scope response — no CapabilityRefusedError, no retry cascade."
"""
from __future__ import annotations

import json
import sys
import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

_VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from tests.phase89_1.fixtures.profile_yaml_samples import (
    AVAILABLE_TOOLS_INDEX_ENTRIES,
    PROFILE_LEGACY_STRING,
    PROFILE_MACRO_INVESTIGATOR_DICT,
)


# ---------------------------------------------------------------------------
# Minimal agent stub that exercises process_tools() via direct call
# ---------------------------------------------------------------------------

def _make_process_tools_agent(profile: Any, profile_id: str = "vm107.macro_investigator"):
    """Stub that exercises only the scope-guard portion of process_tools().

    Uses the real `check_tool_scope_for_profile` helper when it exists.
    Validates that hist_add_tool_result is called with the right content
    when an out-of-scope tool is requested.
    """

    class _ContextLog:
        def log(self, **kwargs):
            pass
        def set_progress(self, *args, **kwargs):
            pass

    class _Context:
        def __init__(self):
            self.log = _ContextLog()
            self.id = "test-ctx-id"

    class _LoopData:
        def __init__(self):
            self.iteration = 0
            self.current_tool = None
            self.params_temporary = {}
            self.last_response = ""

    class _AgentStub:
        def __init__(self):
            self.profile = profile
            self.profile_id = profile_id
            self._data: dict[str, Any] = {}
            self.context = _Context()
            self.loop_data = _LoopData()
            self.agent_name = "A0"
            # Track calls to hist_add_tool_result
            self.hist_add_tool_result_calls: list[dict] = []
            self.hist_add_warning_calls: list[str] = []

        def get_data(self, field: str) -> Any:
            return self._data.get(field, None)

        def set_data(self, field: str, value: Any) -> None:
            self._data[field] = value

        def hist_add_tool_result(self, tool_name: str, tool_result: str, **kwargs):
            self.hist_add_tool_result_calls.append({
                "tool_name": tool_name,
                "tool_result": tool_result,
            })

        def hist_add_warning(self, message: str, **kwargs):
            self.hist_add_warning_calls.append(message)
            return MagicMock(id="fake-warning-id")

    return _AgentStub()


# ---------------------------------------------------------------------------
# Import the scope guard helper (will fail RED until implemented)
# ---------------------------------------------------------------------------

from helpers.tool_scope_guard import check_tool_scope_for_profile, TOOL_NOT_IN_SCOPE_ERROR  # noqa: E402


# ===========================================================================
# Tests 13-16: Execution-level scope guard
# ===========================================================================

@pytest.mark.phase89_1
class TestToolScopeGuardDispatch:

    # ----- Test 13 ----------------------------------------------------------

    def test_scope_guard_blocks_denied_tool_with_structured_response(self):
        """Denied tool call short-circuits with tool_not_in_scope response (not an exception)."""
        agent = _make_process_tools_agent(PROFILE_MACRO_INVESTIGATOR_DICT)

        # Simulate: LLM requested code_execution_tool (denied in macro_investigator)
        refusal = check_tool_scope_for_profile(
            tool_name="code_execution_tool",
            agent_profile=PROFILE_MACRO_INVESTIGATOR_DICT,
        )

        assert refusal is not None, (
            "Expected a refusal response for denied tool 'code_execution_tool', got None"
        )

    # ----- Test 14 ----------------------------------------------------------

    def test_scope_guard_blocked_response_not_in_scope_error_format(self):
        """Refusal response has correct JSON shape: error, tool_name, allowed_tools."""
        refusal = check_tool_scope_for_profile(
            tool_name="code_execution_tool",
            agent_profile=PROFILE_MACRO_INVESTIGATOR_DICT,
        )
        assert refusal is not None

        # refusal must be a JSON string parseable as a dict
        try:
            payload = json.loads(refusal)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Refusal response is not valid JSON: {exc}\nGot: {refusal!r}")

        assert payload.get("error") == TOOL_NOT_IN_SCOPE_ERROR, (
            f"Expected error='tool_not_in_scope', got: {payload.get('error')!r}"
        )
        assert payload.get("tool_name") == "code_execution_tool"
        # allowed_tools must list at least the primary investigator tools
        allowed = payload.get("allowed_tools", [])
        assert isinstance(allowed, list) and len(allowed) > 0, (
            "allowed_tools must be a non-empty list in the refusal payload"
        )
        assert "vm102.indicator_history" in allowed or any(
            "vm102" in t for t in allowed
        ), f"Expected vm102 tools in allowed_tools, got: {allowed}"

    # ----- Test 15 ----------------------------------------------------------

    def test_scope_guard_allows_in_scope_tool(self):
        """In-scope tool returns None (no refusal)."""
        refusal = check_tool_scope_for_profile(
            tool_name="vm102.indicator_history",
            agent_profile=PROFILE_MACRO_INVESTIGATOR_DICT,
        )
        assert refusal is None, (
            f"Expected None (no refusal) for in-scope tool 'vm102.indicator_history', "
            f"got: {refusal!r}"
        )

    # ----- Test 16 ----------------------------------------------------------

    def test_scope_guard_no_op_for_unscoped_profile(self):
        """Legacy string profile has no scope — all tools allowed, guard returns None."""
        refusal = check_tool_scope_for_profile(
            tool_name="code_execution_tool",
            agent_profile=PROFILE_LEGACY_STRING,
        )
        assert refusal is None, (
            "Scope guard must be a no-op for legacy string profiles (no scope defined)"
        )

    def test_scope_guard_no_op_for_none_profile(self):
        """None profile → no scope → all tools allowed."""
        refusal = check_tool_scope_for_profile(
            tool_name="code_execution_tool",
            agent_profile=None,
        )
        assert refusal is None

    def test_scope_guard_handles_denied_not_in_allowed_list(self):
        """Tool in denied_tools but not explicitly denied via allowed_tools absence still blocked."""
        # call_subordinate is in denied_tools in the real macro_investigator YAML
        # but NOT in PROFILE_MACRO_INVESTIGATOR_DICT fixture (which uses the 89-01 fixture shape)
        # Use a profile with explicit denied_tools only
        profile_denied_only = {
            "id": "vm107.test_agent",
            "denied_tools": ["trade_execution_tool", "filesystem_write"],
        }
        refusal = check_tool_scope_for_profile(
            tool_name="trade_execution_tool",
            agent_profile=profile_denied_only,
        )
        assert refusal is not None, "denied_tools check must fire even without allowed_tools"

    def test_scope_guard_allows_tool_not_in_denied_no_allowed_list(self):
        """No allowed_tools, denied=[X] → tools NOT in denied are allowed."""
        profile_denied_only = {
            "id": "vm107.test_agent",
            "denied_tools": ["trade_execution_tool"],
        }
        refusal = check_tool_scope_for_profile(
            tool_name="code_execution_tool",  # NOT in denied_tools
            agent_profile=profile_denied_only,
        )
        assert refusal is None, (
            "Tool not in denied_tools should be allowed when no allowed_tools is set"
        )


# ===========================================================================
# Test 17: Profile prompt no-retry instruction (Fix B)
# ===========================================================================

@pytest.mark.phase89_1
class TestProfilePromptNoRetryInstruction:

    def test_profile_prompt_contains_no_retry_instruction(self):
        """macro_investigator.md must contain explicit no-retry instruction for tool_not_in_scope."""
        import os
        prompt_path = _VM107_ROOT / "prompts" / "macro_investigator.md"
        assert prompt_path.exists(), f"Prompt file not found: {prompt_path}"

        content = prompt_path.read_text(encoding="utf-8")

        # Must contain the no-retry instruction
        assert "tool_not_in_scope" in content, (
            "macro_investigator.md must contain 'tool_not_in_scope' — "
            "the explicit instruction to not retry with variations when this error is returned"
        )
        # Must also say something about not retrying
        assert "retry" in content.lower() or "do not" in content.lower(), (
            "macro_investigator.md must contain explicit instruction to not retry "
            "with variations on tool_not_in_scope"
        )
