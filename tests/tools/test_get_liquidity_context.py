"""Phase 47.2-01 Wave 0 — xfail stub for the get_liquidity_context REAL tool.

Target module: tools.get_liquidity_context
Plan 04 will graduate this xfail spec to GREEN by shipping the
ContractTool subclass that reads Phase 27 layer-6 liquidity primitives
(FVG zones, equal highs/lows, imbalance zones).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_liquidity_context.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_reads_layer_6(mock_polars_scan):
    """get_liquidity_context._call_vm reads parquet at primitives/layer_6/...

    Response shape must include fvg_zones, equal_highs, equal_lows, imbalance_zones.
    """
    from tools.get_liquidity_context import GetLiquidityContext  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 04 implements tools.get_liquidity_context layer-6 read"
    )
