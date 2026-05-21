"""Phase 62.1 — BUG-16 unit tests: ContractTool strips X-* scope headers.

BUG-16 root cause (tools/vm_contracts/base.py ~line 122 — old code):
    ``request = self._validate_request(self.args)``
  The scope-signing extension auto-injects ``X-Agent-Scope`` (and potentially
  other ``X-*`` keys) into ``self.args`` before validation.  Tools whose
  Request models use ``model_config = ConfigDict(extra="forbid")`` raised
  ``ValidationError: Extra inputs not permitted``.

Fix (Plan 62.1-01):
  Strip all X-* prefixed keys from self.args BEFORE _validate_request().
  Log a WARNING listing stripped keys so prompt drift is observable.
  Normal (non-X-prefixed) keys pass through unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ConfigDict

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.base import BaseContract  # noqa: E402
from fingpt_core.contracts.errors import ContractValidationError  # noqa: E402
from helpers.tool import Response  # noqa: E402
from tools.vm_contracts.base import ContractTool  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal test doubles — a simple contract + tool subclass
# ---------------------------------------------------------------------------

class _FooContract(BaseContract):
    """Minimal extra='forbid' contract with a single required field."""
    # BaseContract already sets extra="forbid"; just add a field.
    foo: str


class _FooTool(ContractTool):
    """Minimal ContractTool subclass that validates against _FooContract."""

    def _validate_request(self, args: dict) -> _FooContract:
        try:
            return _FooContract(**args)
        except Exception as e:
            raise ContractValidationError(message=str(e), errors=[str(e)])

    async def _call_vm(self, request: _FooContract) -> dict:
        return {"foo": request.foo}

    def _validate_response(self, data: dict) -> _FooContract:
        try:
            return _FooContract(**data)
        except Exception as e:
            raise ContractValidationError(message=str(e), errors=[str(e)])


def _make_foo_tool(args: dict) -> _FooTool:
    """Return a _FooTool with self.args preset."""
    agent = MagicMock()
    agent.agent_id = "test_agent"
    tool = _FooTool(
        agent=agent,
        name="foo_tool",
        method=None,
        args=args,
        message="",
        loop_data=None,
    )
    return tool


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_contract_tool_strips_x_agent_scope_from_args():
    """ContractTool.execute must strip ``X-Agent-Scope`` before Pydantic validation.

    Reproduces the ``ValidationError: Extra inputs not permitted`` failure seen
    when the scope dispatcher injects ``X-Agent-Scope`` into tool args for tools
    using ``model_config = ConfigDict(extra="forbid")``.
    """
    tool = _make_foo_tool({"foo": "bar", "X-Agent-Scope": "JWT.abc.def"})
    # execute() must NOT raise / return a Contract validation error Response
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    # A validation failure returns message starting with "Contract validation failed"
    assert "Contract validation failed" not in response.message, (
        f"X-Agent-Scope was not stripped — got: {response.message}"
    )
    # args should have X-Agent-Scope removed
    assert "X-Agent-Scope" not in tool.args


def test_contract_tool_strips_any_x_prefixed_key():
    """ContractTool.execute must strip ALL ``X-*`` prefixed keys, not just X-Agent-Scope.

    Future transport-layer injections (X-Correlation-ID, X-Request-ID, etc.)
    should be stripped by the same general rule.
    """
    tool = _make_foo_tool({"foo": "baz", "X-Trace-Id": "trace-123", "X-Request-Id": "req-456"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert "Contract validation failed" not in response.message, (
        f"X-* keys were not stripped — got: {response.message}"
    )
    assert "X-Trace-Id" not in tool.args
    assert "X-Request-Id" not in tool.args


def test_contract_tool_logs_warning_when_stripping(caplog):
    """ContractTool must emit a WARNING log when X-* keys are stripped.

    The log provides an observability signal: if X-* injection patterns change
    upstream, the warning log makes it detectable without test failure.
    """
    tool = _make_foo_tool({"foo": "qux", "X-Agent-Scope": "JWT.xyz"})
    with caplog.at_level(logging.WARNING, logger="fingpt.tools.vm_contracts"):
        asyncio.get_event_loop().run_until_complete(tool.execute())
    assert any(
        "X-Agent-Scope" in record.message and "BUG-16" in record.message
        for record in caplog.records
    ), f"Expected BUG-16 warning; got: {[r.message for r in caplog.records]}"


def test_contract_tool_does_not_strip_normal_keys():
    """ContractTool must NOT strip normal (non-X-prefixed) keys from args.

    This is a baseline regression lock: the X-* strip must be surgical.
    Normal tool parameters must reach _validate_request unchanged.
    """
    tool = _make_foo_tool({"foo": "normal_value"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    # Should succeed (no contract validation failure)
    assert "Contract validation failed" not in response.message, (
        f"Normal key was unexpectedly rejected: {response.message}"
    )
    # The normal key must still be in args
    assert tool.args.get("foo") == "normal_value"
