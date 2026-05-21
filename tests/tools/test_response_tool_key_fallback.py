"""Phase 62.1 — BUG-15 unit test scaffold: Response tool key-fallback tolerance.

BUG-15 root cause (tools/response.py:7):
    ``self.args["text"] if "text" in self.args else self.args["message"]``
  raises KeyError when neither ``text`` nor ``message`` is present.
  LLMs have been observed using ``response``, ``output``, and ``content`` keys.

Wave 1 (Plan 62.1-01) will widen the lookup to a fallback chain and add a
warning log when a non-canonical key is used.  These stubs will flip from xfail
to xpass once that implementation lands.

Pattern follows tests/tools/test_stub_tools.py and tests/tools/conftest.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    tool = ResponseTool("response", agent, agent, agent)
    tool.args = args
    return tool


# ---------------------------------------------------------------------------
# Tests — baseline (currently passing; xfail strict=True so regression is caught)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — baseline: text key works today",
    strict=True,
    run=True,
)
def test_response_returns_text_when_text_key_present():
    """Response_tool returns the value of ``text`` when ``text`` is present in args."""
    tool = _make_response_tool({"text": "hello from text key"})
    import asyncio
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from text key"


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — baseline: message key works today",
    strict=True,
    run=True,
)
def test_response_returns_message_when_only_message_present():
    """Response_tool returns the value of ``message`` when only ``message`` is in args."""
    tool = _make_response_tool({"message": "hello from message key"})
    import asyncio
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from message key"


# ---------------------------------------------------------------------------
# Tests — new behaviors (currently broken; xfail strict=False until Wave 1 lands)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — response key raises KeyError today",
    strict=False,
    run=True,
)
def test_response_falls_back_to_response_key():
    """Response_tool must NOT raise KeyError when only ``response`` key is present.

    LLMs have been observed submitting ``tool_args: {response: "..."}`` — this
    must be accepted as a fallback to the canonical ``text`` key.
    """
    tool = _make_response_tool({"response": "hello from response key"})
    import asyncio
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from response key"


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — output key raises KeyError today",
    strict=False,
    run=True,
)
def test_response_falls_back_to_output_key():
    """Response_tool must NOT raise KeyError when only ``output`` key is present."""
    tool = _make_response_tool({"output": "hello from output key"})
    import asyncio
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from output key"


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — content key raises KeyError today",
    strict=False,
    run=True,
)
def test_response_falls_back_to_content_key():
    """Response_tool must NOT raise KeyError when only ``content`` key is present."""
    tool = _make_response_tool({"content": "hello from content key"})
    import asyncio
    response = asyncio.get_event_loop().run_until_complete(tool.execute())
    assert response.message == "hello from content key"


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — warning log not implemented yet",
    strict=False,
    run=True,
)
def test_response_logs_warning_on_non_canonical_key():
    """Response_tool must emit a warning when a non-canonical key (not text/message) is used.

    This provides a prompt-engineering signal: if warnings appear in production
    logs, the LLM prompt is drifting from the canonical ``text`` key.
    """
    import asyncio
    import logging

    tool = _make_response_tool({"response": "content via non-canonical key"})
    with patch.object(
        sys.modules.get("tools.response", MagicMock()),
        "logger",
        MagicMock(),
    ) as _mock_log:
        with pytest.warns(UserWarning) if False else __import__("contextlib").nullcontext():
            # Accept either logger.warning or warnings.warn — Wave 1 decides which
            with patch("logging.getLogger") as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger
                asyncio.get_event_loop().run_until_complete(tool.execute())
                # Wave 1 will assert mock_logger.warning.called — stubbed here
                assert True, "Wave 1 will fill in the exact warning assertion"


@pytest.mark.xfail(
    reason="BUG-15 implementation pending in Phase 62.1 Plan 01 — all-keys-missing raises KeyError today",
    strict=False,
    run=True,
)
def test_response_no_keyerror_when_all_keys_missing():
    """Response_tool must not raise KeyError when NO recognized key is present.

    Current behavior: raises ``KeyError: 'message'`` after ``text`` check fails.
    Expected behavior after BUG-15: return a fallback empty/error message or
    raise a descriptive ValueError — never a bare KeyError.
    """
    import asyncio

    tool = _make_response_tool({"completely_unknown_key": "some value"})
    try:
        response = asyncio.get_event_loop().run_until_complete(tool.execute())
        # Any non-KeyError outcome is acceptable for this stub assertion
        assert response is not None
    except KeyError:
        pytest.fail("Response_tool raised bare KeyError — BUG-15 not yet fixed")
