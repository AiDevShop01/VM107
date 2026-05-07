"""Phase 47.2-04 — graduated GREEN test for the get_liquidity_context REAL tool.

Target module: tools.get_liquidity_context

Reads Phase 27 layer-6 liquidity primitives directly from parquet
(no VM102 HTTP — Phase 27 has no read endpoint per RESEARCH Critical
Finding #3). Response shape: fvg_zones, equal_highs, equal_lows,
imbalance_zones.
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
async def test_reads_layer_6(monkeypatch, tmp_path):
    """get_liquidity_context._call_vm reads parquet at primitives/layer_6/...

    Response must include fvg_zones, equal_highs, equal_lows, imbalance_zones
    bucketed by `event_type` from the underlying parquet rows.
    """
    from tools.get_liquidity_context import GetLiquidityContext

    # Build a fake data lake with one layer_6 partition.
    data_lake = tmp_path / "lake"
    partition = (
        data_lake
        / "primitives"
        / "layer_6"
        / "instrument=EURUSD"
        / "timeframe=M5"
        / "year=2026"
        / "month=05"
    )
    partition.mkdir(parents=True, exist_ok=True)
    (partition / "part-0.parquet").write_bytes(b"")

    monkeypatch.setenv("FINGPT_DATA_LAKE_PATH", str(data_lake))

    fake_vm100 = MagicMock()
    fake_vm100.get_trade = AsyncMock(return_value={"instrument": "EURUSD"})

    # Build the canonical mixed-event parquet rows the tool will bucket.
    fake_rows = [
        {
            "timestamp": "2026-05-01T00:00:00Z",
            "event_type": "fvg",
            "upper": 1.10,
            "lower": 1.099,
            "direction": "bullish",
            "filled": False,
        },
        {
            "timestamp": "2026-05-01T00:05:00Z",
            "event_type": "equal_high",
            "price": 1.105,
            "swept": False,
        },
        {
            "timestamp": "2026-05-01T00:10:00Z",
            "event_type": "equal_low",
            "price": 1.090,
            "swept": True,
        },
        {
            "timestamp": "2026-05-01T00:15:00Z",
            "event_type": "imbalance",
            "upper": 1.108,
            "lower": 1.103,
            "label": "imbalance",
        },
    ]

    def _fake_scan(files, hive_partitioning=False, **kwargs):  # noqa: ARG001
        fake_lf = MagicMock(name="fake_lf")
        fake_lf.sort.return_value = fake_lf
        fake_lf.head.return_value = fake_lf
        fake_df = MagicMock(name="fake_collected_df")
        fake_df.height = len(fake_rows)
        fake_df.to_dicts.return_value = list(fake_rows)
        fake_lf.collect.return_value = fake_df
        return fake_lf

    monkeypatch.setattr("polars.scan_parquet", _fake_scan, raising=False)

    with patch("tools.get_liquidity_context.VM100Client", return_value=fake_vm100):
        tool = GetLiquidityContext(
            agent=MagicMock(),
            name="get_liquidity_context",
            method=None,
            args={"trade_id": "abc", "timeframe": "M5"},
            message="",
            loop_data=None,
        )
        response = await tool.execute(trade_id="abc", timeframe="M5")

    payload = json.loads(response.message)
    assert payload["trade_id"] == "abc"
    assert payload["instrument"] == "EURUSD"
    assert payload["timeframe"] == "M5"

    assert len(payload["fvg_zones"]) == 1
    assert payload["fvg_zones"][0]["upper"] == 1.10
    assert payload["fvg_zones"][0]["direction"] == "bullish"

    assert len(payload["equal_highs"]) == 1
    assert payload["equal_highs"][0]["price"] == 1.105

    assert len(payload["equal_lows"]) == 1
    assert payload["equal_lows"][0]["swept"] is True

    assert len(payload["imbalance_zones"]) == 1
    assert payload["imbalance_zones"][0]["label"] == "imbalance"


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
@pytest.mark.asyncio
async def test_malformed_envelope_from_vm102_raises():
    """VM102 returns INVALID shape (status=not_available + data=[]) → ContractValidationError."""
    from fingpt_core.contracts.errors import ContractValidationError

    from tools.get_liquidity_context import GetLiquidityContext

    fake_client = MagicMock()
    fake_client.get_liquidity = AsyncMock(
        return_value={"status": "not_available", "data": [], "meta": {"tool": "x"}}
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
        with pytest.raises(ContractValidationError):
            await tool.execute(instrument="EURUSD", timeframe="M5")
