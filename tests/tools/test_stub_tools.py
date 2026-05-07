"""Phase 47.2-01 Wave 0 — xfail stubs for the 5 Tier-3 stub tools.

Target modules: tools.get_macro_context, tools.get_news_context,
                tools.get_regime_context, tools.get_sentiment_context,
                tools.get_performance_history

Plan 05 will graduate these xfail specs to GREEN by shipping the 5 stub
ContractTool subclasses, each returning a NotAvailableResponse with the
locked metadata for its blocking phase.

Locked metadata per stub (from 47.2-CONTEXT.md):
  get_macro_context        → Phase 33, impact HIGH
  get_news_context         → Phase 31, impact HIGH
  get_regime_context       → Phase 34, impact MEDIUM-HIGH
  get_sentiment_context    → Wave 8,   impact LOW-MEDIUM
  get_performance_history  → Phase 47.4 (Wave 5), impact MEDIUM
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


_STUB_TOOLS = [
    "get_macro_context",
    "get_news_context",
    "get_regime_context",
    "get_sentiment_context",
    "get_performance_history",
]


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 05 implements 5 Tier-3 stub tools",
    strict=False,
)
@pytest.mark.parametrize("tool_name", _STUB_TOOLS)
@pytest.mark.asyncio
async def test_stub_payload_shape(tool_name):
    """Each stub returns a NotAvailableResponse with all 6 locked fields populated."""
    import importlib

    importlib.import_module(f"tools.{tool_name}")  # will fail until Plan 05 ships

    pytest.fail(
        f"Wave 0 stub — Plan 05 implements tools.{tool_name} NotAvailableResponse"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 05 implements 5 Tier-3 stub tools",
    strict=False,
)
@pytest.mark.parametrize("tool_name", _STUB_TOOLS)
@pytest.mark.asyncio
async def test_stub_metadata_locked(tool_name):
    """Each stub echoes its locked planned_phase / impact_on_decision per CONTEXT."""
    import importlib

    importlib.import_module(f"tools.{tool_name}")  # will fail until Plan 05 ships

    pytest.fail(
        f"Wave 0 stub — Plan 05 implements tools.{tool_name} locked-metadata fields"
    )
