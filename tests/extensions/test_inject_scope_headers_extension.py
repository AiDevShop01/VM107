"""Phase 60.1 G23: tool_execute_before/_90_inject_scope_headers behavior tests.

Tests verifying:
- Header injection happens when _outbound_headers present
- No-op when absent
- Does not overwrite explicit headers
- Graceful degradation on all edge cases

The extension uses self.agent (set in Extension.__init__) and receives
tool_args/tool_name via **kwargs (matching the actual agent.py call:
  call_extensions_async("tool_execute_before", self, tool_args=tool_args, tool_name=tool_name)
)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _make_extension(agent_data: dict | None = None):
    """Instantiate _90_inject_scope_headers with a mock agent."""
    from extensions.python.tool_execute_before._90_inject_scope_headers import (
        _90_inject_scope_headers,
    )

    agent = MagicMock()
    agent.get_data = MagicMock(side_effect=lambda key: (agent_data or {}).get(key))

    return _90_inject_scope_headers(agent=agent)


@pytest.mark.asyncio
async def test_injects_when_headers_carrier_present():
    """Test 1: headers are injected from _outbound_headers when no explicit headers exist."""
    ext = _make_extension({"_outbound_headers": {"X-Agent-Scope": "jwt-token-here"}})
    tool_args = {"envelope": {}}

    await ext.execute(tool_args=tool_args, tool_name="persist_narrative")

    assert "headers" in tool_args
    assert tool_args["headers"]["X-Agent-Scope"] == "jwt-token-here"


@pytest.mark.asyncio
async def test_preserves_explicit_headers():
    """Test 2: explicit headers set before extension runs are NOT overwritten."""
    ext = _make_extension({"_outbound_headers": {"X-Agent-Scope": "AUTO-INJECTED"}})
    tool_args = {
        "envelope": {},
        "headers": {"X-Agent-Scope": "EXPLICIT"},
    }

    await ext.execute(tool_args=tool_args, tool_name="persist_narrative")

    # Explicit wins — auto-injection must not overwrite
    assert tool_args["headers"]["X-Agent-Scope"] == "EXPLICIT"


@pytest.mark.asyncio
async def test_no_op_when_no_carrier():
    """Test 3: extension is a no-op when agent.data has no _outbound_headers."""
    ext = _make_extension({})  # no _outbound_headers key
    tool_args = {"envelope": {}}

    await ext.execute(tool_args=tool_args, tool_name="persist_narrative")

    # headers should NOT have been added
    assert "headers" not in tool_args


@pytest.mark.asyncio
async def test_no_op_when_tool_args_missing():
    """Test 4: extension is a no-op when tool_args is absent (tools with no args)."""
    ext = _make_extension({"_outbound_headers": {"X-Agent-Scope": "jwt"}})

    # MUST NOT raise — tool_args kwarg absent entirely
    await ext.execute(tool_name="no_args_tool")


@pytest.mark.asyncio
async def test_no_op_when_tool_args_none():
    """Test 5: extension is a no-op when tool_args is explicitly None — graceful degradation."""
    ext = _make_extension({"_outbound_headers": {"X-Agent-Scope": "jwt"}})

    # MUST NOT raise
    await ext.execute(tool_args=None, tool_name="some_tool")


@pytest.mark.asyncio
async def test_no_op_when_agent_none():
    """Test 6: extension is a no-op when agent is None — outside mentor pipeline."""
    from extensions.python.tool_execute_before._90_inject_scope_headers import (
        _90_inject_scope_headers,
    )

    ext = _90_inject_scope_headers(agent=None)
    tool_args = {"envelope": {}}

    # MUST NOT raise
    await ext.execute(tool_args=tool_args, tool_name="persist_narrative")

    # No headers injected because no agent
    assert "headers" not in tool_args
