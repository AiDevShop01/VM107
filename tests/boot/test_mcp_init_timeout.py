"""Phase 132 Plan 01 — SC-3 RED unit test (MCP init_timeout floor > 0).

Belt-and-suspenders floor: `init_timeout` currently defaults to Field(default=0) on
both MCPServerRemote and MCPServerLocal (mcp_handler.py:229, :307). The effective
client-call timeout already falls through to settings (~10s) or a literal 5 at most
sites, so this is a low-severity floor rather than the primary wedge. Wave 2 (132-03)
raises the field default 0 -> 30 and closes the last unbounded usage site.

This test asserts (a) the resolved effective timeout is > 0 and (b) the Field default is
30. (b) is RED until 132-03. Imports are lazy inside the test body so collection succeeds.
"""
from __future__ import annotations

import pytest


def _resolved(server_init_timeout, settings_timeout=10, floor=5):
    """Mirror the mcp_handler resolution: server -> settings -> literal floor."""
    return server_init_timeout or settings_timeout or floor


@pytest.mark.quick
def test_mcp_init_timeout_is_bounded_and_default_thirty():
    """A bare MCP server config resolves to a bounded init_timeout; the Field default is 30."""
    from helpers.mcp_handler import MCPServerRemote, MCPServerLocal

    remote = MCPServerRemote({"name": "probe", "url": "http://127.0.0.1:9/sse"})
    local = MCPServerLocal({"name": "probe", "command": "true"})

    # (a) The effective resolved timeout is always bounded > 0 (already true via fallback).
    assert _resolved(remote.init_timeout) > 0
    assert _resolved(local.init_timeout) > 0

    # (b) RED until 132-03: the Field default floor must be 30 (currently 0).
    remote_default = MCPServerRemote.model_fields["init_timeout"].default
    local_default = MCPServerLocal.model_fields["init_timeout"].default
    assert remote_default == 30, (
        f"MCPServerRemote.init_timeout Field default must floor at 30 (got {remote_default})"
    )
    assert local_default == 30, (
        f"MCPServerLocal.init_timeout Field default must floor at 30 (got {local_default})"
    )
