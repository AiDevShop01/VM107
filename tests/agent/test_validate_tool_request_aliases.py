"""Phase 62.1 Plan 04 — BUG-18 unit tests: validate_tool_request alias tolerance.

BUG-18 root cause (agent.py lines 976-982):
    ``validate_tool_request`` uses strict key lookup (``tool_name`` / ``tool_args``
    only), but ``process_tools`` at lines 881-882 already accepts alias keys
    ``tool`` and ``args`` via ``dict.get`` fallback chaining:

        raw_tool_name = tool_request.get("tool_name", tool_request.get("tool",""))
        tool_args     = tool_request.get("tool_args", tool_request.get("args", {}))

    When the LLM emits ``{"tool": "response", "args": {"text": "..."}}`` the
    dispatcher works fine but the validator raises "tool_name" missing.
    When the LLM emits ``{"tool_name": "x", "tool_args": {}}`` (empty-dict args
    for a zero-arg tool), ``not tool_request.get("tool_args")`` is truthy (empty
    dict is falsy) — so the validator rejects a valid zero-arg call.

Fix (Phase 62.1 Plan 04 — BUG-18):
    Accept ``tool`` as alias for ``tool_name`` and ``args`` as alias for
    ``tool_args``.  Check for ``tool_args is None`` rather than a truthy test so
    empty dict ``{}`` passes for zero-arg tools.

Tests (all 7 must PASS after BUG-18 fix, cases 2+4 fail before fix):
    1. canonical form  {tool_name, tool_args}            → PASS (regression lock)
    2. alias form      {tool, args}                      → PASS (currently FAILS — BUG-18)
    3. mixed form      {tool_name, args}                 → PASS (currently FAILS — BUG-18)
    4. empty-dict args {tool_name, tool_args: {}}        → PASS (currently FAILS — BUG-18)
    5. missing name    {}                                → raises "tool_name (type string)"
    6. missing args    {tool_name, ...}                  → raises "tool_args (type dictionary)"
    7. non-dict input  "not a dict"                      → raises "must be a dictionary"
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Extract validate_tool_request from the Agent class without instantiating it
# (same pattern as test_get_tool_subdir_resolution.py uses for get_tool).
#
# Note: tests/agent/conftest.py ensures the real ``agent`` module is loaded into
# sys.modules BEFORE test_subordinate_invoker_json_extraction can install its
# MagicMock stub.  That conftest is required for this test file to work when
# run as part of the full ``tests/agent/`` suite.
# ---------------------------------------------------------------------------
import agent as _real_agent_module  # noqa: E402 — real module guaranteed by conftest.py

_VALIDATE_TOOL_REQUEST_FN = getattr(
    _real_agent_module.Agent.validate_tool_request,
    "__wrapped__",
    _real_agent_module.Agent.validate_tool_request,
)


def _call_validate(tool_request):
    """Call validate_tool_request with a minimal agent stub."""
    stub = MagicMock(name="AgentStub")
    # Use asyncio.run() to avoid event-loop state contamination when tests run
    # alongside other test files that also use asyncio (e.g. test_subordinate_invoker).
    # asyncio.run() creates a fresh loop per call, which is safe for isolated sync tests.
    return asyncio.run(_VALIDATE_TOOL_REQUEST_FN(stub, tool_request))


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_validate_canonical_form_passes():
    """Case 1 — Canonical {tool_name, tool_args} form must always pass.

    Regression lock — the standard contract shape used by the system prompt
    examples must continue to validate correctly after BUG-18 fix.
    """
    # Must not raise
    _call_validate({"tool_name": "response", "tool_args": {"text": "hello"}})


def test_validate_alias_form_passes():
    """Case 2 — Alias {tool, args} form must pass (BUG-18 fix).

    DeepSeek commonly emits ``{"tool": "...", "args": {...}}`` instead of the
    canonical ``{"tool_name": "...", "tool_args": {...}}``.  The dispatcher
    (lines 881-882) already handles this alias — the validator must match.

    This test FAILS against the un-patched code and PASSES after BUG-18 fix.
    """
    # Must not raise after BUG-18 fix
    _call_validate({"tool": "response", "args": {"text": "hello"}})


def test_validate_mixed_form_passes():
    """Case 3 — Mixed {tool_name, args} form must pass (BUG-18 fix).

    Covers the case where the LLM uses the canonical key for the name but the
    alias key for the args dict.  Dispatcher at line 882 handles this via
    ``tool_request.get("tool_args", tool_request.get("args", {}))`` — the
    validator must accept the same combination.

    This test FAILS against the un-patched code and PASSES after BUG-18 fix.
    """
    _call_validate({"tool_name": "response", "args": {"text": "hello"}})


def test_validate_empty_dict_args_passes():
    """Case 4 — Empty dict tool_args must pass for zero-arg tools (BUG-18 fix).

    The pre-fix validator used ``not tool_request.get("tool_args")`` which is
    truthy (i.e. "failed") for an empty dict ``{}``.  Zero-arg tools — where
    the LLM correctly sends ``{"tool_name": "x", "tool_args": {}}`` — were
    being rejected.

    This test FAILS against the un-patched code and PASSES after BUG-18 fix.
    """
    _call_validate({"tool_name": "response", "tool_args": {}})


@pytest.mark.parametrize("bad_request", [
    {},
    {"tool_args": {"text": "x"}},         # only args key, no name key at all
    {"tool_name": None, "tool_args": {}},  # name key present but None
    {"tool_name": 42, "tool_args": {}},    # name key present but wrong type
])
def test_validate_missing_name_raises(bad_request):
    """Case 5 — Requests with no resolvable tool name raise a clear error.

    Both the canonical ``tool_name`` and alias ``tool`` paths must be absent
    (or non-string) for this error to trigger.  The error message must mention
    'tool_name (type string)' so callers know the expected field name.
    """
    with pytest.raises(ValueError, match="tool_name"):
        _call_validate(bad_request)


@pytest.mark.parametrize("bad_request", [
    {"tool_name": "response"},                         # no args key at all
    {"tool_name": "response", "tool_args": None},      # explicit None for tool_args, no args alias
    {"tool_name": "response", "tool_args": "string"},  # string instead of dict
    {"tool_name": "response", "tool_args": 42},        # int instead of dict
])
def test_validate_missing_args_raises(bad_request):
    """Case 6 — Requests with no resolvable tool_args dict raise a clear error.

    Both ``tool_args`` and the alias ``args`` must be absent/non-dict for this
    error to trigger.  The error message must mention 'tool_args (type dictionary)'.
    """
    with pytest.raises(ValueError, match="tool_args"):
        _call_validate(bad_request)


def test_validate_non_dict_input_raises():
    """Case 7 — A non-dict tool request raises 'must be a dictionary'.

    Baseline lock — the outer type guard must still fire before any field
    inspection happens.
    """
    with pytest.raises(ValueError, match="must be a dictionary"):
        _call_validate("not a dict")

    with pytest.raises(ValueError, match="must be a dictionary"):
        _call_validate(["tool_name", "response"])

    with pytest.raises(ValueError, match="must be a dictionary"):
        _call_validate(None)
