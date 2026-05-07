"""Phase 47.2-04 — graduated GREEN tests for the get_trade_context REAL tool.

Target module: tools.get_trade_context
Wave 0 stub graduated to real assertions per Plan 04 done-criteria.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.asyncio
async def test_calls_vm100_with_trade_id(mock_vm100_client):
    """get_trade_context._call_vm forwards trade_id and returns typed contract."""
    from tools.get_trade_context import GetTradeContext

    # Patch VM100Client constructor inside the tool module so it returns our mock.
    with patch("tools.get_trade_context.VM100Client", return_value=mock_vm100_client):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"trade_id": "abc123"},
            message="",
            loop_data=None,
        )
        response = await tool.execute(trade_id="abc123")

    # The mock client must have been asked for the right trade_id.
    mock_vm100_client.get_trade.assert_awaited_once_with("abc123")

    # Response message is JSON-serialised contract: instrument from the canned trade.
    payload = json.loads(response.message)
    assert payload["trade_id"] == "abc123"
    assert payload["instrument"] == "EURUSD"
    assert payload["direction"] == "short"
    assert payload["strategy_id"] == "model_2_option_1_short"
    assert response.break_loop is False
