"""Phase 62.1 — BUG-15 unit tests: Response tool key-fallback tolerance.

BUG-15 root cause (tools/response.py — old code):
    ``self.args["text"] if "text" in self.args else self.args["message"]``
  raised KeyError when neither ``text`` nor ``message`` was present.
  LLMs have been observed using ``response``, ``output``, and ``content`` keys.

Fix (Plan 62.1-01):
  Lookup order: ``text`` > ``message`` > ``response`` > ``output`` > ``content``.
  Falls back to ``str(self.args)`` when no recognized key is present (no KeyError).
  Logs WARNING on non-canonical key; logs ERROR on total miss.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from tools.response import ResponseTool  # noqa: E402


# ---------------------------------------------------------------------------
# Helper — build a minimal ResponseTool instance with given args dict
# ---------------------------------------------------------------------------

def _make_response_tool(args: dict) -> ResponseTool:
    """Return a ResponseTool whose self.args is set to *args*."""
    agent = MagicMock()
    agent.agent_id = "test_agent"
    tool = ResponseTool(
        agent=agent,
        name="response",
        method=None,
        args=args,
        message="",
        loop_data=None,
    )
    return tool


# ---------------------------------------------------------------------------
# Tests — baseline (canonical keys still work)
# ---------------------------------------------------------------------------


def test_response_returns_text_when_text_key_present():
    """ResponseTool returns the value of ``text`` when ``text`` is present in args."""
    tool = _make_response_tool({"text": "hello from text key"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from text key"


def test_response_returns_message_when_only_message_present():
    """ResponseTool returns the value of ``message`` when only ``message`` is in args."""
    tool = _make_response_tool({"message": "hello from message key"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from message key"


# ---------------------------------------------------------------------------
# Tests — fallback behaviors (BUG-15 fix)
# ---------------------------------------------------------------------------


def test_response_falls_back_to_response_key():
    """ResponseTool must NOT raise KeyError when only ``response`` key is present.

    LLMs have been observed submitting ``tool_args: {response: "..."}`` — this
    must be accepted as a fallback to the canonical ``text`` key.
    """
    tool = _make_response_tool({"response": "hello from response key"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from response key"


def test_response_falls_back_to_output_key():
    """ResponseTool must NOT raise KeyError when only ``output`` key is present."""
    tool = _make_response_tool({"output": "hello from output key"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from output key"


def test_response_falls_back_to_content_key():
    """ResponseTool must NOT raise KeyError when only ``content`` key is present."""
    tool = _make_response_tool({"content": "hello from content key"})
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from content key"


def test_response_logs_warning_on_non_canonical_key(caplog):
    """ResponseTool must emit a WARNING when a non-canonical key is used.

    This provides a prompt-engineering signal: if warnings appear in production
    logs, the LLM prompt is drifting from the canonical ``text`` key.
    """
    tool = _make_response_tool({"response": "content via non-canonical key"})
    with caplog.at_level(logging.WARNING, logger="fingpt.tools.response"):
        asyncio.get_event_loop().run_until_complete(tool.execute())
    assert any(
        "non-canonical key" in record.message and "response" in record.message
        for record in caplog.records
    ), f"Expected warning about non-canonical key; got records: {[r.message for r in caplog.records]}"


def test_response_no_keyerror_when_all_keys_missing():
    """ResponseTool must not raise KeyError when NO recognized key is present.

    Expected behavior after BUG-15: return str(args) as last resort — never a bare KeyError.
    """
    tool = _make_response_tool({"completely_unknown_key": "some value"})
    # Must not raise KeyError
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response is not None
    # Returns stringified args as last resort
    assert "completely_unknown_key" in response.message
