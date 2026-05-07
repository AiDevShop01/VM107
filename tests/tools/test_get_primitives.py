"""Phase 47.2-01 Wave 0 — xfail stubs for the get_primitives REAL tool.

Target module: tools.get_primitives
Plan 04 will graduate these xfail specs to GREEN by shipping the
ContractTool subclass that reads layers L1+L2+L4+L6 ONLY.

V1 layer scope (per 47.2-CONTEXT.md):
  L1 — Volatility & Range
  L2 — Structure
  L4 — Compression
  L6 — Liquidity (Phase 27 already shipped)

Layers 3, 5, 7+ are out-of-scope and must raise ContractValidationError.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_primitives.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_reads_layers_1_2_4_6(mock_polars_scan):
    """get_primitives request with layers=[1,2,4,6] reads parquet for each layer."""
    from tools.get_primitives import GetPrimitives  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 04 implements tools.get_primitives layer fan-out"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 04 implements tools/get_primitives.py",
    strict=False,
)
@pytest.mark.asyncio
async def test_excludes_other_layers():
    """get_primitives request with layers=[3] raises ContractValidationError.

    Layer scoping is enforced at the Pydantic Literal boundary on
    GetPrimitivesV1Request (see Plan 02). Any non-{1,2,4,6} layer must reject.
    """
    from tools.get_primitives import GetPrimitives  # noqa: F401

    pytest.fail(
        "Wave 0 stub — Plan 04 implements tools.get_primitives layer scope guard"
    )
