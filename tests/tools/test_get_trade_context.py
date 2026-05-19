"""Phase 58.1 Plan 02 — graduated GREEN tests for the dual-ID resolver tool.

Target module: tools.get_trade_context

Phase 58.1 amendment (REQ-58.1-F4):
  - Tool accepts EITHER trade_id (Execution UUID or api.Trade.id int) OR
    journal_id (TradeJournal UUID).
  - Tool calls VM100 GET /api/journal/internal/resolve-trade-identity FIRST,
    then GET /api/v1/trades/{trade_id} only when the resolver returns a
    numeric trade_id.
  - Tool returns the canonical 6-field NotAvailableResponse on resolver
    miss — NOT GetTradeContextResponse with None fields (Phase 47.2 lock).
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CANNED_TRADE = {
    "trade_id": "987654321",
    "instrument": "EURUSD",
    "direction": "short",
    "strategy_id": "model_2_option_1_short",
    "entry_price": 1.0950,
    "stop_loss_price": 1.0975,
    "take_profit_price": 1.0900,
    "timeframe": "M5",
    "notes": "Compression at HTF resistance.",
}


_CANNED_RESOLVER_HIT = {
    "input_id": "987654321",
    "input_kind": "trade_id",
    "trade_id": 987654321,
    "execution_id": "11111111-1111-1111-1111-111111111111",
    "journal_id": "22222222-2222-2222-2222-222222222222",
    "found": True,
}


def _client_mock_two_calls(resolver_payload: dict, trade_payload: dict) -> MagicMock:
    """Build a VM100Client mock where .get() returns resolver then trade in order."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=[resolver_payload, trade_payload])
    return client


def _client_mock_one_call(resolver_payload: dict) -> MagicMock:
    """Build a VM100Client mock where .get() returns the resolver payload only.

    Used when the test exercises a path that should short-circuit before the
    second /api/v1/trades/{id} call (resolver-miss, DRAFT journal).
    """
    client = MagicMock()
    client.get = AsyncMock(return_value=resolver_payload)
    return client


def _client_mock_raises(*errors) -> MagicMock:
    """Build a VM100Client mock where each .get() call raises one of `errors`."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(errors))
    return client


# ---------------------------------------------------------------------------
# Happy paths — dual-ID resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calls_resolver_with_trade_id():
    """Tool calls resolver first with trade_id, then trade-detail endpoint."""
    from tools.get_trade_context import GetTradeContext
    from fingpt_core.contracts.agents.trade_context import GetTradeContextRequest

    client_mock = _client_mock_two_calls(_CANNED_RESOLVER_HIT, _CANNED_TRADE)
    with patch("tools.get_trade_context.VM100Client", return_value=client_mock):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"trade_id": "987654321"},
            message="",
            loop_data=None,
        )
        result = await tool._call_vm(GetTradeContextRequest(trade_id="987654321"))

    # Two calls: resolver, then trade detail.
    assert client_mock.get.await_count == 2
    first_call = client_mock.get.await_args_list[0]
    assert "resolve-trade-identity" in first_call.args[0]
    second_call = client_mock.get.await_args_list[1]
    assert "api/v1/trades/987654321" in second_call.args[0]

    # Response carries the resolved trade fields.
    assert result["instrument"] == "EURUSD"
    assert result["direction"] == "short"
    assert result["strategy_id"] == "model_2_option_1_short"


@pytest.mark.asyncio
async def test_both_id_kinds_same_payload():
    """get_trade_context(trade_id=int) and get_trade_context(journal_id=uuid)
    resolve to the same payload when the resolver returns the same identity
    triple. RESEARCH § "Sample inputs that must resolve to same payload".
    """
    from tools.get_trade_context import GetTradeContext
    from fingpt_core.contracts.agents.trade_context import GetTradeContextRequest

    # Resolver-payload-for-int and resolver-payload-for-uuid both echo the
    # same canonical (execution_id, journal_id, trade_id) triple.
    resolver_payload_int = {
        **_CANNED_RESOLVER_HIT,
        "input_id": "987654321",
        "input_kind": "trade_id",
    }
    resolver_payload_uuid = {
        **_CANNED_RESOLVER_HIT,
        "input_id": "22222222-2222-2222-2222-222222222222",
        "input_kind": "journal_id",
    }

    # Call 1: trade_id
    client_int = _client_mock_two_calls(resolver_payload_int, _CANNED_TRADE)
    with patch("tools.get_trade_context.VM100Client", return_value=client_int):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"trade_id": "987654321"},
            message="",
            loop_data=None,
        )
        r_int = await tool._call_vm(
            GetTradeContextRequest(trade_id="987654321")
        )

    # Call 2: journal_id
    client_uuid = _client_mock_two_calls(resolver_payload_uuid, _CANNED_TRADE)
    with patch("tools.get_trade_context.VM100Client", return_value=client_uuid):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"journal_id": "22222222-2222-2222-2222-222222222222"},
            message="",
            loop_data=None,
        )
        r_uuid = await tool._call_vm(
            GetTradeContextRequest(
                journal_id="22222222-2222-2222-2222-222222222222"
            )
        )

    # The trade_id echo will differ (it's the input echo), but every other
    # field is identical because they both resolved to the same trade.
    r_int_no_id = {k: v for k, v in r_int.items() if k != "trade_id"}
    r_uuid_no_id = {k: v for k, v in r_uuid.items() if k != "trade_id"}
    assert r_int_no_id == r_uuid_no_id, (
        f"Payloads diverge:\nint: {r_int_no_id}\nuuid: {r_uuid_no_id}"
    )


# ---------------------------------------------------------------------------
# NotAvailable paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bogus_id_returns_not_available():
    """Resolver 404 → tool returns NotAvailableResponse (not GetTradeContextResponse)."""
    from tools.get_trade_context import GetTradeContext
    from fingpt_core.contracts.agents.trade_context import GetTradeContextRequest

    # httpx.HTTPStatusError-equivalent — Exception subclass is enough for the
    # tool's except-block to catch.
    client_mock = _client_mock_raises(Exception("404 from resolver"))
    with patch("tools.get_trade_context.VM100Client", return_value=client_mock):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"trade_id": "bogus"},
            message="",
            loop_data=None,
        )
        result = await tool._call_vm(
            GetTradeContextRequest(trade_id="bogus")
        )

    assert result["status"] == "not_available"
    assert result["tool"] == "get_trade_context"
    assert result["planned_phase"] == "58.1"
    # Resolver was called exactly once — no trade-detail call after miss.
    assert client_mock.get.await_count == 1


@pytest.mark.asyncio
async def test_resolver_returns_found_false_yields_not_available():
    """Resolver 200 with found=False → tool returns NotAvailableResponse."""
    from tools.get_trade_context import GetTradeContext
    from fingpt_core.contracts.agents.trade_context import GetTradeContextRequest

    resolver_miss_200 = {
        "input_id": "abc",
        "found": False,
        "tried": ["trade_id_int"],
    }
    client_mock = _client_mock_one_call(resolver_miss_200)
    with patch("tools.get_trade_context.VM100Client", return_value=client_mock):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"trade_id": "abc"},
            message="",
            loop_data=None,
        )
        result = await tool._call_vm(
            GetTradeContextRequest(trade_id="abc")
        )

    assert result["status"] == "not_available"


@pytest.mark.asyncio
async def test_not_available_shape():
    """The not-available payload has exactly the 6 required fields.

    Six fields per fingpt_core.contracts.agents.not_available.NotAvailableResponse:
      status, planned_phase, tool, would_provide, impact_on_decision, unblocks_when

    NO ``reason`` field (Phase 58.1 RESEARCH correction #2 — the older
    4-field shape with ``reason`` does NOT exist). The unblock reason is
    encoded inside unblocks_when[0] as a human-readable string.
    """
    from tools.get_trade_context import GetTradeContext
    from fingpt_core.contracts.agents.trade_context import GetTradeContextRequest

    client_mock = _client_mock_raises(Exception("404"))
    with patch("tools.get_trade_context.VM100Client", return_value=client_mock):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"trade_id": "bogus"},
            message="",
            loop_data=None,
        )
        result = await tool._call_vm(
            GetTradeContextRequest(trade_id="bogus")
        )

    keys = set(result.keys())
    assert keys == {
        "status",
        "planned_phase",
        "tool",
        "would_provide",
        "impact_on_decision",
        "unblocks_when",
    }, f"Unexpected NotAvailable shape: {keys}"
    assert "reason" not in keys
    assert isinstance(result["would_provide"], list)
    assert isinstance(result["unblocks_when"], list)
    assert result["impact_on_decision"] in {"HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# DRAFT journal path — resolver returns trade_id=None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_journal_returns_response_with_null_fields():
    """Resolver returns trade_id=None (DRAFT journal) → tool returns a
    GetTradeContextResponse-shaped payload with the echoed input ID and
    None fields. NOT a NotAvailableResponse — the LLM still has the journal
    handle to work with (the journal exists, just no executed Trade row yet).
    """
    from tools.get_trade_context import GetTradeContext
    from fingpt_core.contracts.agents.trade_context import GetTradeContextRequest

    resolver_draft = {
        "input_id": "22222222-2222-2222-2222-222222222222",
        "input_kind": "journal_id",
        "trade_id": None,
        "execution_id": None,
        "journal_id": "22222222-2222-2222-2222-222222222222",
        "found": True,
    }
    client_mock = _client_mock_one_call(resolver_draft)
    with patch("tools.get_trade_context.VM100Client", return_value=client_mock):
        tool = GetTradeContext(
            agent=MagicMock(),
            name="get_trade_context",
            method=None,
            args={"journal_id": "22222222-2222-2222-2222-222222222222"},
            message="",
            loop_data=None,
        )
        result = await tool._call_vm(
            GetTradeContextRequest(
                journal_id="22222222-2222-2222-2222-222222222222"
            )
        )

    # GetTradeContextResponse shape — trade_id echo + None fields. NOT a
    # NotAvailableResponse (status would be absent for the response branch).
    assert "status" not in result
    assert result["trade_id"] == "22222222-2222-2222-2222-222222222222"
    assert result["instrument"] is None
    assert result["direction"] is None
    # No trade-detail call — resolver returned trade_id=None.
    assert client_mock.get.await_count == 1
