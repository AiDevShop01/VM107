"""Phase 47.2-05 — graduated GREEN tests for the 5 Tier-3 stub tools.

Target modules: tools.get_macro_context, tools.get_news_context,
                tools.get_regime_context, tools.get_sentiment_context,
                tools.get_performance_history

Each stub returns a NotAvailableResponse with locked metadata so Phase 47.3
Decision Framework V1 can reduce confidence appropriately. Stubs are
idempotent + stateless — pure constant returns, zero side effects.

Locked metadata per stub (from 47.2-CONTEXT.md):
  get_macro_context        -> Phase 33,    impact HIGH
  get_news_context         -> Phase 31,    impact HIGH
  get_regime_context       -> Phase 34,    impact MEDIUM
  get_sentiment_context    -> Wave 8,      impact LOW
  get_performance_history  -> Phase 47.4,  impact MEDIUM
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# (tool_name, class_name, planned_phase, would_provide, impact, unblocks_when)
_STUB_LOCK = [
    (
        "get_macro_context",
        "GetMacroContext",
        "Phase 33",
        ["interest_rate_decisions", "inflation_data", "central_bank_bias"],
        "HIGH",
        ["Phase 33 complete", "Macro ingestion pipeline active"],
    ),
    (
        "get_news_context",
        "GetNewsContext",
        "Phase 31",
        ["scheduled_events", "breaking_headlines", "event_proximity"],
        "HIGH",
        ["Phase 31 complete", "News pipeline active"],
    ),
    (
        "get_regime_context",
        "GetRegimeContext",
        "Phase 34",
        ["trend_regime", "volatility_regime", "correlation_regime"],
        "MEDIUM",
        ["Phase 34 complete"],
    ),
    (
        "get_sentiment_context",
        "GetSentimentContext",
        "Wave 8",
        ["retail_positioning", "options_skew", "social_sentiment"],
        "LOW",
        ["Wave 8 sentiment service shipped"],
    ),
    (
        "get_performance_history",
        "GetPerformanceHistory",
        "Phase 47.4",
        ["strategy_win_rate", "recent_drawdown", "similar_setup_outcomes"],
        "MEDIUM",
        ["Phase 47.4 complete", "Postgres trade-evaluation history populated"],
    ),
]


@pytest.mark.parametrize(
    "tool_name,class_name,planned_phase,would_provide,impact,unblocks_when",
    _STUB_LOCK,
    ids=[row[0] for row in _STUB_LOCK],
)
@pytest.mark.asyncio
async def test_stub_payload_shape(
    tool_name, class_name, planned_phase, would_provide, impact, unblocks_when
):
    """Each stub instantiates and returns a Response whose JSON body has all 6 NotAvailableResponse fields."""
    module = importlib.import_module(f"tools.{tool_name}")
    cls = getattr(module, class_name)

    tool = cls(
        agent=MagicMock(),
        name=tool_name,
        method=None,
        args={"trade_id": "abc-123"},
        message="",
        loop_data=None,
    )
    response = await tool.execute(trade_id="abc-123")

    payload = json.loads(response.message)
    # All 6 locked fields must be populated
    assert payload["status"] == "not_available"
    assert payload["planned_phase"] == planned_phase
    assert payload["tool"] == tool_name
    assert payload["would_provide"] == would_provide
    assert payload["impact_on_decision"] == impact
    assert payload["unblocks_when"] == unblocks_when
    assert response.break_loop is False


@pytest.mark.parametrize(
    "tool_name,class_name,planned_phase,would_provide,impact,unblocks_when",
    _STUB_LOCK,
    ids=[row[0] for row in _STUB_LOCK],
)
def test_stub_metadata_locked(
    tool_name, class_name, planned_phase, would_provide, impact, unblocks_when
):
    """Each stub's class-level _STUB constant exact-matches the CONTEXT.md table."""
    module = importlib.import_module(f"tools.{tool_name}")
    cls = getattr(module, class_name)

    stub = cls._STUB
    assert stub.status == "not_available"
    assert stub.planned_phase == planned_phase
    assert stub.tool == tool_name
    assert stub.would_provide == would_provide
    assert stub.impact_on_decision == impact
    assert stub.unblocks_when == unblocks_when
