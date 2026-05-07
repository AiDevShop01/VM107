"""get_liquidity_context — read Phase 27 layer-6 liquidity primitives from parquet.

Phase 47.2 Tier-2 real tool. Phase 27 has NO HTTP read endpoint
(RESEARCH Critical Finding #3) — direct parquet read for FVG zones,
equal highs/lows, imbalance zones. Idempotent + stateless.

The underlying layer_6 parquet is row-keyed by `event_type` (one of
`fvg`, `equal_high`, `equal_low`, `imbalance`). The tool buckets rows
into the four typed sub-models from
`fingpt_core.contracts.agents.liquidity_context`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import polars as pl

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.agents.liquidity_context import (
    GetLiquidityContextRequest,
    GetLiquidityContextResponse,
)
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError

from tools.vm_contracts.base import ContractTool


class GetLiquidityContext(ContractTool):
    """LLM-callable: get_liquidity_context(trade_id, timeframe, lookback_bars?)."""

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetLiquidityContextRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetLiquidityContextRequest) -> dict:
        instrument = await self._resolve_instrument(request.trade_id)
        data_lake = os.getenv("FINGPT_DATA_LAKE_PATH", "/mnt/parquet_prod")
        base = Path(data_lake) / "primitives" / "layer_6"
        instrument_dir = (
            base
            / f"instrument={instrument}"
            / f"timeframe={request.timeframe}"
        )

        empty: dict[str, Any] = {
            "trade_id": request.trade_id,
            "instrument": instrument,
            "timeframe": request.timeframe,
            "fvg_zones": [],
            "equal_highs": [],
            "equal_lows": [],
            "imbalance_zones": [],
        }

        if not instrument_dir.exists():
            return empty

        files = list(instrument_dir.glob("year=*/month=*/*.parquet"))
        if not files:
            return empty

        try:
            df = (
                pl.scan_parquet(
                    [str(f) for f in files], hive_partitioning=True
                )
                .sort("timestamp", descending=True)
                .head(request.lookback_bars)
                .collect()
            )
        except Exception:
            return empty

        bars = df.to_dicts()
        fvg = [b for b in bars if b.get("event_type") == "fvg"]
        eq_high = [b for b in bars if b.get("event_type") == "equal_high"]
        eq_low = [b for b in bars if b.get("event_type") == "equal_low"]
        imb = [b for b in bars if b.get("event_type") == "imbalance"]

        return {
            "trade_id": request.trade_id,
            "instrument": instrument,
            "timeframe": request.timeframe,
            "fvg_zones": [
                {
                    "timestamp": b["timestamp"],
                    "upper": b["upper"],
                    "lower": b["lower"],
                    "direction": b.get("direction", "bullish"),
                    "filled": b.get("filled", False),
                }
                for b in fvg
            ],
            "equal_highs": [
                {
                    "timestamp": b["timestamp"],
                    "price": b["price"],
                    "swept": b.get("swept", False),
                }
                for b in eq_high
            ],
            "equal_lows": [
                {
                    "timestamp": b["timestamp"],
                    "price": b["price"],
                    "swept": b.get("swept", False),
                }
                for b in eq_low
            ],
            "imbalance_zones": [
                {
                    "timestamp": b["timestamp"],
                    "upper": b["upper"],
                    "lower": b["lower"],
                    "label": b.get("label", "imbalance"),
                }
                for b in imb
            ],
        }

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return GetLiquidityContextResponse(**data)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _resolve_instrument(self, trade_id: str) -> str:
        client = VM100Client(profile=RetryProfile.FAST_FAIL)
        if hasattr(client, "get_trade"):
            trade = await client.get_trade(trade_id)  # type: ignore[attr-defined]
        else:
            trade = await client.get(f"api/v1/trades/{trade_id}")
        return trade["instrument"]
