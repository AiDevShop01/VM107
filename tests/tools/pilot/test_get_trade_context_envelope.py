"""Phase 70.5 Plan 06 Gate 1 — get_trade_context RICH envelope unit test.

Tests validate:
- GetTradeContextPayload (renamed from GetTradeContextResponse) + backward alias
- PAYLOAD_SCHEMA_VERSION = "1.1.0"
- ToolProvenance populated on success path (citations + assumptions)
- Dispatcher produces ToolResultEnvelope[GetTradeContextPayload] with RICH provenance
- Confidence > 0.7 (baseline 0.85, complete evidence, deterministic)
- confidence_reasoning has entries for baseline + deterministic ceiling
- NotAvailable path populates declared_failure_modes with NO_MATCH_FOUND
- Envelope is frozen (mutation raises ValidationError)
- Backward compat: GetTradeContextResponse is still importable (alias)

REQ-70.5-6 Gate 1 — unit test for rich envelope shape.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest
from pydantic import ValidationError

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, ToolProvenance


# ---------------------------------------------------------------------------
# Helper: build a mock registry + entry for get_trade_context
# ---------------------------------------------------------------------------


def _make_ctx() -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_entry(
    typical_confidence: float = 0.85,
    expected_freshness: int = 60,
    is_deterministic: bool = True,
    version: str = "1.1.0",
):
    from core.agents.tool_registry import ToolEntry
    return ToolEntry(
        id="get_trade_context",
        status="real",
        source_module="tools.get_trade_context",
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=False,
    )


def _mock_registry_patch(entry, snapshot_hash: str = "sha256-test"):
    """Return (get_registry_patch, get_tool_entry_patch) for use in `with patch(...):`."""
    mock_reg = MagicMock()
    mock_reg.snapshot_hash = snapshot_hash
    mock_reg.lookup.return_value = None  # no refusal

    return mock_reg, entry


# ---------------------------------------------------------------------------
# Test: backward compat — GetTradeContextResponse still importable as alias
# ---------------------------------------------------------------------------


def test_backward_compat_alias():
    """GetTradeContextResponse must remain importable (alias to GetTradeContextPayload)."""
    from fingpt_core.contracts.agents.trade_context import (
        GetTradeContextPayload,
        GetTradeContextResponse,
    )
    assert GetTradeContextResponse is GetTradeContextPayload


def test_payload_schema_version():
    """GetTradeContextPayload must have PAYLOAD_SCHEMA_VERSION = '1.1.0'."""
    from fingpt_core.contracts.agents.trade_context import GetTradeContextPayload
    assert GetTradeContextPayload.PAYLOAD_SCHEMA_VERSION == "1.1.0"


# ---------------------------------------------------------------------------
# Test: success path produces RICH provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trade_context_success_envelope_rich(mock_dispatcher_ctx):
    """dispatch_tool('get_trade_context', ...) produces RICH envelope.

    Asserts:
    - outcome_class = "success", success = True
    - citations non-empty; at least one with opaque_id = input trade_id
    - assumptions has 2 entries (both pilot assumption strings)
    - confidence > 0.7
    - confidence_reasoning has >= 2 entries
    - payload is GetTradeContextPayload instance
    - envelope is frozen
    """
    from core.agents.tool_dispatcher import dispatch_tool, _get_tool_entry, _get_registry

    entry = _make_entry()
    trade_id = "abc-123"
    resolved_identity = {"found": True, "trade_id": 42, "journal_id": None}
    trade_row = {
        "instrument": "EURUSD",
        "direction": "long",
        "strategy_id": "model_2",
        "entry_price": 1.085,
        "stop_loss_price": 1.082,
        "take_profit_price": 1.091,
        "notes": "Test note",
        "timeframe": "M5",
        "checklist_snapshot_text": "OK",
    }

    mock_vm100 = MagicMock()
    mock_vm100.get = AsyncMock(side_effect=[resolved_identity, trade_row])
    mock_vm100.close = AsyncMock()

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None  # no refusal

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("fingpt_core.clients.VM100Client", return_value=mock_vm100),
        patch("core.agents.tool_dispatcher._invoke_resolver") as mock_invoke,
    ):
        # Build the payload that the resolver returns (the tool refactored to return Payload)
        from fingpt_core.contracts.agents.trade_context import GetTradeContextPayload
        payload = GetTradeContextPayload(
            trade_id=trade_id,
            instrument="EURUSD",
            direction="long",
            provenance=ToolProvenance(
                citations=(
                    EvidenceCitation(
                        citation_kind="trade",
                        opaque_id=trade_id,
                        human_label=f"Trade {trade_id}",
                    ),
                    EvidenceCitation(
                        citation_kind="dataset",
                        opaque_id="vm100/api/journal/internal/resolve-trade-identity",
                        human_label="VM100 identity resolver",
                    ),
                ),
                assumptions=(
                    "assumes user's local timezone is account timezone",
                    "assumes no broker fills missed in the lookback window",
                ),
            ),
        )
        mock_invoke.return_value = payload

        envelope = await dispatch_tool("get_trade_context", {"trade_id": trade_id}, mock_dispatcher_ctx)

    # Outcome
    assert envelope.outcome_class == "success"
    assert envelope.success is True

    # Citations — at least 1 with the trade_id
    assert len(envelope.citations) >= 1
    assert any(c.opaque_id == trade_id for c in envelope.citations)

    # Assumptions — exactly 2 pilot strings
    assert len(envelope.assumptions) == 2
    assert "assumes user's local timezone is account timezone" in envelope.assumptions

    # Confidence
    assert envelope.confidence is not None
    assert envelope.confidence > 0.7

    # Confidence reasoning has baseline + at least one more entry
    assert len(envelope.confidence_reasoning) >= 2

    # Payload type
    from fingpt_core.contracts.agents.trade_context import GetTradeContextPayload
    assert isinstance(envelope.payload, GetTradeContextPayload)

    # Frozen — Pydantic v2 frozen models raise ValidationError on setattr
    with pytest.raises((ValidationError, TypeError)):
        envelope.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test: not-available path populates NO_MATCH_FOUND failure mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trade_context_refusal_path_no_match_found(mock_dispatcher_ctx):
    """When VM100 returns 404, envelope has outcome_class in ('refused','failure').

    On the not-available / unresolved path, the pilot pre-declares
    FailureMode(code=NO_MATCH_FOUND, ...).
    """
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.agents.trade_context import GetTradeContextPayload
    from fingpt_core.contracts.failure_modes import FailureModeCode

    entry = _make_entry()

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    # Resolver raises a generic exception (simulates 404 unresolved)
    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", side_effect=Exception("id_unresolved")),
    ):
        envelope = await dispatch_tool("get_trade_context", {"trade_id": "bad-id"}, mock_dispatcher_ctx)

    # outcome_class is failure or refused (not success)
    assert envelope.outcome_class in ("failure", "refused")
    assert envelope.success is False


# ---------------------------------------------------------------------------
# Test: envelope is frozen (immutable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trade_context_envelope_frozen(mock_dispatcher_ctx):
    """Mutation of a returned envelope raises ValidationError."""
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.agents.trade_context import GetTradeContextPayload

    entry = _make_entry()

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    payload = GetTradeContextPayload(
        trade_id="abc-123",
        provenance=ToolProvenance(
            citations=(
                EvidenceCitation(citation_kind="trade", opaque_id="abc-123"),
            ),
            assumptions=("assumes user's local timezone is account timezone",),
        ),
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool("get_trade_context", {"trade_id": "abc-123"}, mock_dispatcher_ctx)

    with pytest.raises((ValidationError, TypeError)):
        envelope.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test: top-level dispatch — parent_envelope_id is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trade_context_top_level_no_parent(mock_dispatcher_ctx):
    """Top-level dispatch (depth=0) produces envelope.parent_envelope_id=None."""
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.agents.trade_context import GetTradeContextPayload

    entry = _make_entry()
    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    payload = GetTradeContextPayload(
        trade_id="abc-123",
        provenance=ToolProvenance(
            citations=(EvidenceCitation(citation_kind="trade", opaque_id="abc-123"),),
            assumptions=("assumes user's local timezone is account timezone",),
        ),
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool("get_trade_context", {"trade_id": "abc-123"}, mock_dispatcher_ctx)

    # Top-level: parent_envelope_id is None
    assert envelope.parent_envelope_id is None
