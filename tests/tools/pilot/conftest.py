"""Phase 70.5 Plan 06 — shared fixtures for pilot tool envelope tests.

Provides:
- mock_dispatcher_ctx   — a top-level InvocationContext (depth=0)
- make_mock_entry       — factory producing a ToolEntry with Plan 05 pilot values
- mock_vm100_client_get_trade_context — VM100Client mock returning resolved trade
- mock_vm100_client_not_found — VM100Client mock that raises on identity resolve
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure VM107 root is on sys.path
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.invocation_context import InvocationContext


# ---------------------------------------------------------------------------
# Core shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_dispatcher_ctx() -> InvocationContext:
    """Top-level InvocationContext (depth=0, no parent) for pilot tests."""
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        conversation_id=None,
        execution_depth=0,
    )


def make_mock_entry(
    tool_id: str = "get_trade_context",
    typical_confidence: float = 0.85,
    expected_freshness_seconds: int = 60,
    is_deterministic: bool = True,
    version: str = "1.1.0",
    status: str = "real",
):
    """Factory for a mock ToolEntry with Plan 05 author-judgment values."""
    from core.agents.tool_registry import ToolEntry

    return ToolEntry(
        id=tool_id,
        status=status,
        source_module=f"tools.{tool_id}",
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness_seconds,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=False,
    )


@pytest.fixture
def mock_entry_get_trade_context():
    """ToolEntry for get_trade_context with Plan 05 values (confidence=0.85, det=true)."""
    return make_mock_entry("get_trade_context", 0.85, 60, True, "1.1.0")


@pytest.fixture
def mock_entry_behavioral_analysis():
    """ToolEntry for behavioral_analysis_tool (confidence=0.75, det=true)."""
    return make_mock_entry("behavioral_analysis_tool", 0.75, 60, True, "1.0.0")


@pytest.fixture
def mock_entry_execution_quality():
    """ToolEntry for execution_quality_tool (confidence=0.80, det=true)."""
    return make_mock_entry("execution_quality_tool", 0.80, 30, True, "1.0.0")


# ---------------------------------------------------------------------------
# VM100 client helpers for get_trade_context
# ---------------------------------------------------------------------------


def _make_canned_resolved_identity(trade_id: str = "abc-123"):
    """Return a canned identity-resolution hit from VM100."""
    return {
        "found": True,
        "trade_id": 42,
        "journal_id": None,
        "execution_id": None,
    }


def _make_canned_trade(trade_id: int = 42):
    """Return a canned trade row from VM100 GET /api/v1/trades/{id}."""
    return {
        "id": trade_id,
        "instrument": "EURUSD",
        "direction": "long",
        "strategy_id": "model_2_option_1_long",
        "entry_price": 1.0850,
        "stop_loss_price": 1.0820,
        "take_profit_price": 1.0910,
        "notes": "H4 compression breakout.",
        "timeframe": "M5",
        "checklist_snapshot_text": "All criteria met.",
        "last_evaluation": None,
    }
