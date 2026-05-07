"""Phase 47.2.1-05 — graduated GREEN tests for the refactored get_liquidity_context tool.

Target module: tools.get_liquidity_context

The tool is a pure typed transport against VM102 (no Polars, no filesystem,
no VM100 hop). Takes `instrument` directly from Tier-1 context. Active-only
filtering is computed server-side by VM102 (Plan 04 — left-anti join against
the Phase 28 events stream).

Note: The legacy `test_reads_layer_6` GREEN test from Phase 47.2-04 has been
DELETED — it tested the deprecated `trade_id` + Polars + VM100 hop path that
no longer exists. Its behavior is now covered by `test_calls_vm102_no_polars`
plus the embedded-status envelope round-trip in test_chat_to_vm102_smoke.py.
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


# =============================================================================
# Phase 47.2.1 Wave 0 — xfail specs for the refactored tool (instrument input,
# no Polars, no FS, VM102Client.get_liquidity).
#
# Graduates to GREEN when Plan 47.2.1-05 ships the rewritten tool body.
# =============================================================================


_pytestmark_wave0 = pytest.mark.xfail(
    reason=(
        "Wave 0: refactored get_liquidity_context (instrument input, no Polars, no FS, "
        "VM102Client.get_liquidity) ships in Plan 47.2.1-05."
    ),
    strict=False,
)


@_pytestmark_wave0
@pytest.mark.asyncio
async def test_calls_vm102_no_polars():
    """Refactored tool calls VM102Client.get_liquidity; never imports/uses Polars."""
    from tools.get_liquidity_context import GetLiquidityContext

    fake_client = MagicMock()
    fake_client.get_liquidity = AsyncMock(
        return_value={
            "status": "ok",
            "data": {
                "instrument": "EURUSD",
                "timeframe": "M5",
                "fvg_zones": [],
                "equal_highs": [],
                "equal_lows": [],
                "imbalance_zones": [],
            },
            "meta": None,
        }
    )
    fake_client.close = AsyncMock()

    with patch("tools.get_liquidity_context.VM102Client", return_value=fake_client):
        tool = GetLiquidityContext(
            agent=MagicMock(),
            name="get_liquidity_context",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5"},
            message="",
            loop_data=None,
        )
        await tool.execute(instrument="EURUSD", timeframe="M5")

    fake_client.get_liquidity.assert_called_once()
    kwargs = fake_client.get_liquidity.call_args.kwargs
    assert kwargs.get("instrument") == "EURUSD"
    assert "trade_id" not in kwargs


@_pytestmark_wave0
@pytest.mark.asyncio
async def test_silent_lookback_clamp():
    """lookback_bars=9999 → clamped to 500 before client call."""
    from tools.get_liquidity_context import GetLiquidityContext

    fake_client = MagicMock()
    fake_client.get_liquidity = AsyncMock(
        return_value={
            "status": "ok",
            "data": {
                "instrument": "EURUSD",
                "timeframe": "M5",
                "fvg_zones": [],
                "equal_highs": [],
                "equal_lows": [],
                "imbalance_zones": [],
            },
            "meta": None,
        }
    )
    fake_client.close = AsyncMock()

    with patch("tools.get_liquidity_context.VM102Client", return_value=fake_client):
        tool = GetLiquidityContext(
            agent=MagicMock(),
            name="get_liquidity_context",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5", "lookback_bars": 9999},
            message="",
            loop_data=None,
        )
        await tool.execute(instrument="EURUSD", timeframe="M5", lookback_bars=9999)

    kwargs = fake_client.get_liquidity.call_args.kwargs
    assert kwargs.get("lookback_bars") == 500


@_pytestmark_wave0
def test_request_rejects_trade_id():
    """Passing trade_id (legacy) → ContractValidationError (extra=forbid)."""
    from fingpt_core.contracts.errors import ContractValidationError

    from tools.get_liquidity_context import GetLiquidityContext

    tool = GetLiquidityContext(
        agent=MagicMock(),
        name="get_liquidity_context",
        method=None,
        args={"trade_id": "abc", "timeframe": "M5"},
        message="",
        loop_data=None,
    )
    with pytest.raises(ContractValidationError):
        tool._validate_request({"trade_id": "abc", "timeframe": "M5"})


@_pytestmark_wave0
@pytest.mark.asyncio
async def test_transport_failure_synthesizes_not_available():
    """httpx.ConnectError from client → tool synthesizes status:not_available envelope."""
    import httpx

    from tools.get_liquidity_context import GetLiquidityContext

    fake_client = MagicMock()
    fake_client.get_liquidity = AsyncMock(
        side_effect=httpx.ConnectError("VM102 unreachable")
    )
    fake_client.close = AsyncMock()

    with patch("tools.get_liquidity_context.VM102Client", return_value=fake_client):
        tool = GetLiquidityContext(
            agent=MagicMock(),
            name="get_liquidity_context",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5"},
            message="",
            loop_data=None,
        )
        response = await tool.execute(instrument="EURUSD", timeframe="M5")

    payload = json.loads(response.message)
    assert payload["status"] == "not_available"
    assert payload["data"] is None
    assert payload["meta"] is not None
    assert payload["meta"]["tool"] == "get_liquidity_context"


@_pytestmark_wave0
def test_malformed_envelope_from_vm102_raises():
    """VM102 returns INVALID shape (status=not_available + data=[]) → _validate_response raises ContractValidationError.

    Note: ContractTool.execute() catches ContractValidationError and returns a
    Response object with break_loop=False (agent-friendly). The boundary
    enforcement contract is on `_validate_response` itself — that's what this
    test asserts. Per Plan 02 model_validator, status="not_available" + data=[]
    is the ambiguous shape forbidden by CONTEXT.md §2 invalid shape #1.
    """
    from fingpt_core.contracts.errors import ContractValidationError

    from tools.get_liquidity_context import GetLiquidityContext

    tool = GetLiquidityContext(
        agent=MagicMock(),
        name="get_liquidity_context",
        method=None,
        args={"instrument": "EURUSD", "timeframe": "M5"},
        message="",
        loop_data=None,
    )
    with pytest.raises(ContractValidationError):
        tool._validate_response(
            {"status": "not_available", "data": [], "meta": {"tool": "x"}}
        )
