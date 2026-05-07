"""Phase 47.2-04 — graduated GREEN tests for the get_primitives REAL tool.

Target module: tools.get_primitives

V1 layer scope (per 47.2-CONTEXT.md):
  L1 — Volatility & Range
  L2 — Structure
  L4 — Compression
  L6 — Liquidity (Phase 27 already shipped)

Layers 3, 5, 7+ are out-of-scope and must raise ContractValidationError
at request validation time (Pydantic Literal on GetPrimitivesV1Request).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.mark.asyncio
async def test_reads_layers_1_2_4_6(monkeypatch, tmp_path):
    """get_primitives request with layers=[1,2,4,6] reads parquet for each layer."""
    from tools.get_primitives import GetPrimitives

    # Fake data lake on tmp_path with one parquet stub per V1 layer.
    data_lake = tmp_path / "lake"
    for layer in (1, 2, 4, 6):
        partition = (
            data_lake
            / "primitives"
            / f"layer_{layer}"
            / "instrument=EURUSD"
            / "timeframe=M5"
            / "year=2026"
            / "month=05"
        )
        partition.mkdir(parents=True, exist_ok=True)
        (partition / "part-0.parquet").write_bytes(b"")  # placeholder

    monkeypatch.setenv("FINGPT_DATA_LAKE_PATH", str(data_lake))

    # Mock the VM100 client used by _resolve_instrument so we don't hit network.
    fake_vm100 = MagicMock()
    fake_vm100.get_trade = AsyncMock(return_value={"instrument": "EURUSD"})

    # Mock polars.scan_parquet to return a fake LazyFrame with predictable height.
    layers_seen: list[int] = []

    def _fake_scan(files, hive_partitioning=False, **kwargs):  # noqa: ARG001
        # Identify which layer we're scanning by inspecting the file path.
        sample = str(files[0]) if files else ""
        for layer in (1, 2, 4, 6):
            if f"layer_{layer}" in sample:
                layers_seen.append(layer)
                break
        fake_lf = MagicMock(name=f"fake_lf_{sample}")
        fake_lf.sort.return_value = fake_lf
        fake_lf.head.return_value = fake_lf
        fake_df = MagicMock(name="fake_collected_df")
        fake_df.height = 3
        fake_df.to_dicts.return_value = [{"timestamp": "2026-05-01T00:00:00Z"}]
        fake_lf.collect.return_value = fake_df
        return fake_lf

    monkeypatch.setattr("polars.scan_parquet", _fake_scan, raising=False)

    with patch("tools.get_primitives.VM100Client", return_value=fake_vm100):
        tool = GetPrimitives(
            agent=MagicMock(),
            name="get_primitives",
            method=None,
            args={"trade_id": "abc", "timeframe": "M5", "layers": [1, 2, 4, 6]},
            message="",
            loop_data=None,
        )
        response = await tool.execute(
            trade_id="abc", timeframe="M5", layers=[1, 2, 4, 6]
        )

    # All four layers should have been read.
    assert sorted(layers_seen) == [1, 2, 4, 6], (
        f"Expected scans for layers 1/2/4/6, got {sorted(layers_seen)}"
    )

    # Response message contains the contract dump — sanity-check structure.
    import json

    payload = json.loads(response.message)
    assert payload["trade_id"] == "abc"
    assert payload["instrument"] == "EURUSD"
    assert payload["timeframe"] == "M5"
    assert {layer["layer"] for layer in payload["layers"]} == {1, 2, 4, 6}
    for layer_block in payload["layers"]:
        assert layer_block["count"] == 3


def test_excludes_other_layers():
    """Layers outside {1,2,4,6} are rejected at the Pydantic boundary."""
    from fingpt_core.contracts.errors import ContractValidationError

    from tools.get_primitives import GetPrimitives

    tool = GetPrimitives(
        agent=MagicMock(),
        name="get_primitives",
        method=None,
        args={"trade_id": "abc", "timeframe": "M5", "layers": [3]},
        message="",
        loop_data=None,
    )

    with pytest.raises(ContractValidationError):
        tool._validate_request(
            {"trade_id": "abc", "timeframe": "M5", "layers": [3]}
        )
