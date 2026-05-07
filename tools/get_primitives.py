"""get_primitives — read pre-computed primitives from parquet for L1, L2, L4, L6 only.

Phase 47.2 V1 scope: L1 (Volatility/Range), L2 (Structure), L4 (Compression),
L6 (Liquidity). Direct parquet reads via Polars (NO VM102 HTTP — VM102 has no
read endpoint per RESEARCH Critical Finding #2). Idempotent + stateless
(CONTEXT lock — no DB writes, no recompute side-effects, no caching).

Layer scope is enforced at the Pydantic Literal boundary on
`GetPrimitivesV1Request.layers` — invalid layers raise
`ContractValidationError` at request validation, never reach the parquet
reader.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import polars as pl

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.features.primitives_v1 import (
    GetPrimitivesV1Request,
    GetPrimitivesV1Response,
)

from tools.vm_contracts.base import ContractTool


class GetPrimitives(ContractTool):
    """LLM-callable: get_primitives(trade_id, timeframe, layers?, lookback_bars?)."""

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetPrimitivesV1Request(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetPrimitivesV1Request) -> dict:
        instrument = await self._resolve_instrument(request.trade_id)
        data_lake = os.getenv("FINGPT_DATA_LAKE_PATH", "/mnt/parquet_prod")

        layers_out: list[dict[str, Any]] = []
        for layer in request.layers:
            base = Path(data_lake) / "primitives" / f"layer_{layer}"
            instrument_dir = (
                base
                / f"instrument={instrument}"
                / f"timeframe={request.timeframe}"
            )

            if not instrument_dir.exists():
                layers_out.append({"layer": layer, "count": 0, "bars": []})
                continue

            files = list(instrument_dir.glob("year=*/month=*/*.parquet"))
            if not files:
                layers_out.append({"layer": layer, "count": 0, "bars": []})
                continue

            try:
                df = (
                    pl.scan_parquet(
                        [str(f) for f in files], hive_partitioning=True
                    )
                    .sort("timestamp", descending=True)
                    .head(request.lookback_bars)
                    .collect()
                )
                layers_out.append(
                    {
                        "layer": layer,
                        "count": df.height,
                        "bars": df.to_dicts(),
                    }
                )
            except Exception:
                # Per-layer graceful degradation (CONTEXT.md "graceful per-section").
                layers_out.append({"layer": layer, "count": 0, "bars": []})

        return {
            "trade_id": request.trade_id,
            "instrument": instrument,
            "timeframe": request.timeframe,
            "layers": layers_out,
        }

    def _validate_response(self, data: dict) -> BaseContract:
        try:
            return GetPrimitivesV1Response(**data)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _resolve_instrument(self, trade_id: str) -> str:
        client = VM100Client(profile=RetryProfile.FAST_FAIL)
        if hasattr(client, "get_trade"):
            trade = await client.get_trade(trade_id)  # type: ignore[attr-defined]
        else:
            trade = await client.get(f"api/v1/trades/{trade_id}")
        return trade["instrument"]
