"""Phase 47.2-01 Wave 0 — xfail stub for the get_trade_context REAL tool.

Target module: tools.get_trade_context
Plan 04 will graduate this xfail spec to GREEN by shipping the
ContractTool subclass that wraps VM100Client.get_trade(trade_id).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_trade_context.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_calls_vm100_with_trade_id(mock_vm100_client):
    """get_trade_context._call_vm forwards trade_id to VM100Client.get_trade."""
    from tools.get_trade_context import GetTradeContext  # noqa: F401

    pytest.fail("Wave 0 stub — Plan 04 implements tools.get_trade_context.GetTradeContext")
