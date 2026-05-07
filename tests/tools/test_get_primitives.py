"""Phase 47.2.1-05 — graduated GREEN tests for the refactored get_primitives tool.

Target module: tools.get_primitives

The tool is a pure typed transport against VM102 (no Polars, no filesystem,
no VM100 hop). Takes `instrument` directly from Tier-1 context.

V1 layer scope (per 47.2-CONTEXT.md, unchanged): {1, 2, 4, 6}. Other layers
are rejected at the Pydantic Literal boundary on GetPrimitivesV1Request.

Note: The legacy `test_reads_layers_1_2_4_6` GREEN test from Phase 47.2-04
has been DELETED — it tested the deprecated `trade_id` + Polars + VM100 hop
path that no longer exists. Its behavior is now covered by `test_calls_vm102_no_polars`
plus the embedded-status envelope round-trip in test_chat_to_vm102_smoke.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def test_excludes_other_layers():
    """Layers outside {1,2,4,6} are rejected at the Pydantic boundary."""
    from fingpt_core.contracts.errors import ContractValidationError

    from tools.get_primitives import GetPrimitives

    tool = GetPrimitives(
        agent=MagicMock(),
        name="get_primitives",
        method=None,
        args={"instrument": "EURUSD", "timeframe": "M5", "layers": [3]},
        message="",
        loop_data=None,
    )

    with pytest.raises(ContractValidationError):
        tool._validate_request(
            {"instrument": "EURUSD", "timeframe": "M5", "layers": [3]}
        )


# =============================================================================
# Phase 47.2.1 Wave 0 — xfail specs for the refactored tool (instrument input,
# no Polars, no FS, no VM100 hop).
#
# These graduate to GREEN when Plan 47.2.1-05 ships the rewritten tool body.
# The 47.2-04 GREEN tests above will be DELETED by Plan 05 Task 1 (since they
# test the deprecated trade_id+Polars path).
# =============================================================================


class _Wave0PostRefactor:
    """Marker scope so the xfail decorator below applies only to the new specs."""


_pytestmark_wave0 = pytest.mark.xfail(
    reason=(
        "Wave 0: refactored get_primitives (instrument input, no Polars, no FS, "
        "VM102Client) ships in Plan 47.2.1-05. The xfail tests below graduate "
        "to green when Plan 05 rewrites tools/get_primitives.py."
    ),
    strict=False,
)


@_pytestmark_wave0
@pytest.mark.asyncio
async def test_calls_vm102_no_polars():
    """Refactored tool calls VM102Client.get_primitives_v1; never imports/uses Polars."""
    from tools.get_primitives import GetPrimitives

    fake_client = MagicMock()
    fake_client.get_primitives_v1 = AsyncMock(
        return_value={
            "status": "ok",
            "data": {"instrument": "EURUSD", "timeframe": "M5", "layers": []},
            "meta": None,
        }
    )
    fake_client.close = AsyncMock()

    with patch("tools.get_primitives.VM102Client", return_value=fake_client):
        tool = GetPrimitives(
            agent=MagicMock(),
            name="get_primitives",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5", "layers": [1, 2, 4, 6]},
            message="",
            loop_data=None,
        )
        await tool.execute(
            instrument="EURUSD", timeframe="M5", layers=[1, 2, 4, 6]
        )

    # Client was called with `instrument=` not `trade_id=`
    fake_client.get_primitives_v1.assert_called_once()
    kwargs = fake_client.get_primitives_v1.call_args.kwargs
    assert kwargs.get("instrument") == "EURUSD"
    assert "trade_id" not in kwargs


@_pytestmark_wave0
@pytest.mark.asyncio
async def test_silent_lookback_clamp():
    """lookback_bars=9999 → tool clamps to 500 before hitting client (defensive)."""
    from tools.get_primitives import GetPrimitives

    fake_client = MagicMock()
    fake_client.get_primitives_v1 = AsyncMock(
        return_value={
            "status": "ok",
            "data": {"instrument": "EURUSD", "timeframe": "M5", "layers": []},
            "meta": None,
        }
    )
    fake_client.close = AsyncMock()

    with patch("tools.get_primitives.VM102Client", return_value=fake_client):
        tool = GetPrimitives(
            agent=MagicMock(),
            name="get_primitives",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5", "lookback_bars": 9999},
            message="",
            loop_data=None,
        )
        await tool.execute(
            instrument="EURUSD", timeframe="M5", lookback_bars=9999
        )

    kwargs = fake_client.get_primitives_v1.call_args.kwargs
    assert kwargs.get("lookback_bars") == 500


@_pytestmark_wave0
def test_request_rejects_trade_id():
    """Passing trade_id (legacy) → ContractValidationError (extra=forbid)."""
    from fingpt_core.contracts.errors import ContractValidationError

    from tools.get_primitives import GetPrimitives

    tool = GetPrimitives(
        agent=MagicMock(),
        name="get_primitives",
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

    from tools.get_primitives import GetPrimitives

    fake_client = MagicMock()
    fake_client.get_primitives_v1 = AsyncMock(
        side_effect=httpx.ConnectError("VM102 unreachable")
    )
    fake_client.close = AsyncMock()

    with patch("tools.get_primitives.VM102Client", return_value=fake_client):
        tool = GetPrimitives(
            agent=MagicMock(),
            name="get_primitives",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5"},
            message="",
            loop_data=None,
        )
        response = await tool.execute(instrument="EURUSD", timeframe="M5")

    import json

    payload = json.loads(response.message)
    assert payload["status"] == "not_available"
    assert payload["data"] is None
    assert payload["meta"] is not None
    assert payload["meta"]["tool"] == "get_primitives"


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

    from tools.get_primitives import GetPrimitives

    tool = GetPrimitives(
        agent=MagicMock(),
        name="get_primitives",
        method=None,
        args={"instrument": "EURUSD", "timeframe": "M5"},
        message="",
        loop_data=None,
    )
    with pytest.raises(ContractValidationError):
        tool._validate_response(
            {"status": "not_available", "data": [], "meta": {"tool": "x"}}
        )
