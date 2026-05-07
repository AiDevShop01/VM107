"""Phase 47.2-07 — Tier-1 lightweight context builder.

Target module: core.agents.tier1_context
Plan 07 graduates these specs from Plan 01's xfail stubs.

build_tier1_context(journal_id) MUST:
  - return a curated dict with locked top-level keys
    (trade_id, instrument, direction, strategy_id,
     last_evaluation, journal_metadata)
  - degrade gracefully per-section: if get_current_evaluation
    fails, last_evaluation is None but everything else is filled
  - take journal_id ONLY (NOT inline context dict)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


_LOCKED_TIER1_KEYS = {
    "trade_id",
    "instrument",
    "direction",
    "strategy_id",
    "last_evaluation",
    "journal_metadata",
}


@pytest.mark.asyncio
async def test_build_returns_curated_dict(mocker):
    """build_tier1_context returns dict with the locked Tier-1 keys."""
    from core.agents import tier1_context

    fake_journal = {
        "trade_id": "trade-abc",
        "checklist_snapshot_text": "snapshot text",
    }
    fake_trade = {
        "id": "trade-abc",
        "instrument": "EURUSD",
        "direction": "short",
        "strategy_id": "model_2_option_1_short",
        "entry_price": 1.0950,
        "stop_loss_price": 1.0975,
        "take_profit_price": 1.0900,
        "timeframe": "M5",
    }
    fake_eval = {
        "evaluation_id": "eval-1",
        "recommendation": "PROCEED",
        "score": 5,
        "confidence": "MEDIUM",
        "created_at": "2026-05-07T00:00:00Z",
    }

    mocker.patch.object(
        tier1_context.VM100Client, "get_journal",
        new=AsyncMock(return_value=fake_journal),
    )
    mocker.patch.object(
        tier1_context.VM100Client, "get_trade",
        new=AsyncMock(return_value=fake_trade),
    )
    mocker.patch.object(
        tier1_context.VM100Client, "get_current_evaluation",
        new=AsyncMock(return_value=fake_eval),
    )

    result = await tier1_context.build_tier1_context("journal-xyz")

    # Locked top-level keys present
    assert set(result.keys()) == _LOCKED_TIER1_KEYS

    # Curated values flow through correctly
    assert result["trade_id"] == "trade-abc"
    assert result["instrument"] == "EURUSD"
    assert result["direction"] == "short"
    assert result["strategy_id"] == "model_2_option_1_short"

    # Last evaluation summary
    assert result["last_evaluation"] is not None
    assert result["last_evaluation"]["evaluation_id"] == "eval-1"
    assert result["last_evaluation"]["recommendation"] == "PROCEED"
    assert result["last_evaluation"]["score"] == 5
    assert result["last_evaluation"]["confidence"] == "MEDIUM"

    # Journal metadata sub-dict
    md = result["journal_metadata"]
    assert md["timeframe"] == "M5"
    assert md["checklist_snapshot_text"] == "snapshot text"
    assert md["entry_price"] == 1.0950
    assert md["stop_loss_price"] == 1.0975
    assert md["take_profit_price"] == 1.0900


@pytest.mark.asyncio
async def test_partial_when_postgres_unavailable(mocker):
    """When get_current_evaluation raises, builder still returns full dict
    with last_evaluation: None (graceful per-section degradation)."""
    from core.agents import tier1_context

    fake_journal = {"trade_id": "trade-abc", "checklist_snapshot_text": None}
    fake_trade = {
        "id": "trade-abc",
        "instrument": "GBPUSD",
        "direction": "long",
        "strategy_id": None,
        "entry_price": None,
        "stop_loss_price": None,
        "take_profit_price": None,
        "timeframe": "H1",
    }

    mocker.patch.object(
        tier1_context.VM100Client, "get_journal",
        new=AsyncMock(return_value=fake_journal),
    )
    mocker.patch.object(
        tier1_context.VM100Client, "get_trade",
        new=AsyncMock(return_value=fake_trade),
    )
    mocker.patch.object(
        tier1_context.VM100Client, "get_current_evaluation",
        new=AsyncMock(side_effect=ConnectionError("postgres down")),
    )

    result = await tier1_context.build_tier1_context("journal-xyz")

    # All locked keys still present
    assert set(result.keys()) == _LOCKED_TIER1_KEYS

    # Full data from VM100 still flows
    assert result["instrument"] == "GBPUSD"
    assert result["direction"] == "long"
    assert result["strategy_id"] is None  # journal had no strategy_id

    # Graceful: last_evaluation is None instead of raising
    assert result["last_evaluation"] is None


@pytest.mark.asyncio
async def test_uses_journal_id_only(mocker):
    """Builder accepts a single positional journal_id arg — never an inline
    context dict (Wave 1 deprecation)."""
    import inspect

    from core.agents import tier1_context

    sig = inspect.signature(tier1_context.build_tier1_context)
    params = list(sig.parameters.values())
    # Exactly one parameter: journal_id
    assert len(params) == 1
    assert params[0].name == "journal_id"

    # Smoke: invoking with positional journal_id produces the curated dict
    mocker.patch.object(
        tier1_context.VM100Client, "get_journal",
        new=AsyncMock(return_value={"trade_id": "t", "checklist_snapshot_text": None}),
    )
    mocker.patch.object(
        tier1_context.VM100Client, "get_trade",
        new=AsyncMock(return_value={
            "id": "t", "instrument": "X", "direction": "long",
            "strategy_id": None, "entry_price": None,
            "stop_loss_price": None, "take_profit_price": None,
            "timeframe": None,
        }),
    )
    mocker.patch.object(
        tier1_context.VM100Client, "get_current_evaluation",
        new=AsyncMock(return_value=None),
    )

    result = await tier1_context.build_tier1_context("journal-xyz")
    assert set(result.keys()) == _LOCKED_TIER1_KEYS
