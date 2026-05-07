"""Phase 47.2.1 Wave 0 — End-to-end smoke harness for chat → tool → VM102.

XFAIL until Plan 47.2.1-05 ships the rewritten tools (no Polars, no VM100 hop)
AND Plan 47.2.1-02 ships VM102Client.get_primitives_v1 / get_liquidity.

Uses httpx.MockTransport to fake the VM102 wire — no real network calls.

2 specs:
- test_get_primitives_e2e         — tool → VM102Client.get_primitives_v1 → fake VM102 → envelope OK
- test_get_liquidity_context_e2e  — tool → VM102Client.get_liquidity → fake VM102 → envelope OK
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


pytestmark = pytest.mark.xfail(
    reason=(
        "Wave 0 — refactored tools + extended VM102Client ship in Plans "
        "47.2.1-02 and 47.2.1-05. E2E harness graduates to green when both "
        "land."
    ),
    strict=False,
)


@pytest.mark.asyncio
async def test_get_primitives_e2e():
    """End-to-end: tool dispatch → VM102Client.get_primitives_v1 → mocked VM102 wire."""
    import httpx

    from tools.get_primitives import GetPrimitives

    def handler(request: httpx.Request) -> httpx.Response:
        # Verify the wire shape is correct (path + query params)
        assert request.method == "GET"
        assert request.url.path.endswith("/api/v1/primitives/")
        assert request.url.params.get("instrument") == "EURUSD"
        assert request.url.params.get("timeframe") == "M5"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "data": {
                    "instrument": "EURUSD",
                    "timeframe": "M5",
                    "layers": [{"layer": 2, "count": 0, "bars": []}],
                },
                "meta": None,
            },
        )

    transport = httpx.MockTransport(handler)

    # Patch VM102Client to use mocked transport
    with patch("fingpt_core.clients.vm102_client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance._transport = transport
        instance.get = httpx.AsyncClient(transport=transport).get

        tool = GetPrimitives(
            agent=MagicMock(),
            name="get_primitives",
            method=None,
            args={"instrument": "EURUSD", "timeframe": "M5"},
            message="",
            loop_data=None,
        )
        response = await tool.execute(instrument="EURUSD", timeframe="M5")

    payload = json.loads(response.message)
    assert payload["status"] == "ok"
    assert payload["data"]["instrument"] == "EURUSD"
    assert payload["meta"] is None


@pytest.mark.asyncio
async def test_get_liquidity_context_e2e():
    """End-to-end: tool dispatch → VM102Client.get_liquidity → mocked VM102 wire."""
    import httpx

    from tools.get_liquidity_context import GetLiquidityContext

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/api/v1/liquidity/")
        assert request.url.params.get("instrument") == "EURUSD"
        return httpx.Response(
            200,
            json={
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
            },
        )

    transport = httpx.MockTransport(handler)

    with patch("fingpt_core.clients.vm102_client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance._transport = transport
        instance.get = httpx.AsyncClient(transport=transport).get

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
    assert payload["status"] == "ok"
    assert payload["data"]["instrument"] == "EURUSD"
    assert payload["meta"] is None
