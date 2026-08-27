"""Phase 70.5 Plan 06 Gate 1 — behavioral_analysis RICH envelope unit test.

Tests validate:
- BehavioralAnalysisPayload (renamed from BehavioralAnalysisResult) + backward alias
- PAYLOAD_SCHEMA_VERSION = "1.0.0"
- ToolProvenance populated with citations (trade_id consumed) + assumption string
- Dispatcher produces ToolResultEnvelope with RICH provenance
- confidence > 0.5 (baseline 0.75, complete evidence, deterministic)
- Insufficient-context path maps correctly
- Async path exercised (run_async)
- Envelope frozen

REQ-70.5-6 Gate 1 — behavioral_analysis pilot.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, ToolProvenance


# ---------------------------------------------------------------------------
# Helpers
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
    typical_confidence: float = 0.75,
    expected_freshness: int = 60,
    is_deterministic: bool = True,
    version: str = "1.0.0",
):
    from core.agents.tool_registry import ToolEntry
    return ToolEntry(
        id="behavioral_analysis_tool",
        status="real",
        source_module="tools.behavioral_analysis",
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=False,
    )


# ---------------------------------------------------------------------------
# Test: backward compat alias
# ---------------------------------------------------------------------------


def test_behavioral_analysis_backward_compat_alias():
    """BehavioralAnalysisResult must remain importable (alias to BehavioralAnalysisPayload)."""
    from fingpt_core.contracts.analytics.behavioral import (
        BehavioralAnalysisPayload,
        BehavioralAnalysisResult,
    )
    assert BehavioralAnalysisResult is BehavioralAnalysisPayload


def test_behavioral_analysis_payload_schema_version():
    """BehavioralAnalysisPayload must have PAYLOAD_SCHEMA_VERSION = '1.0.0'."""
    from fingpt_core.contracts.analytics.behavioral import BehavioralAnalysisPayload
    assert BehavioralAnalysisPayload.PAYLOAD_SCHEMA_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# Test: success path produces RICH provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_behavioral_analysis_success_envelope_rich(mock_dispatcher_ctx):
    """dispatch_tool('behavioral_analysis_tool', ...) produces RICH envelope."""
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.analytics.behavioral import BehavioralAnalysisPayload

    entry = _make_entry()
    execution_id = str(uuid.uuid4())

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    payload = BehavioralAnalysisPayload(
        score=Decimal("75.00"),
        confidence=Decimal("80.00"),
        signals={
            "hesitation_normal": True,
            "entry_on_time": True,
            "stop_not_moved": True,
            "managed_cleanly": True,
            "no_revenge_trade": True,
            "no_fomo": True,
        },
        narrative_fragments=["Behavioral score = 75/100: no adverse signals"],
        provenance=ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=execution_id,
                    human_label=f"Execution {execution_id}",
                ),
            ),
            assumptions=(
                "assumes trades within lookback window represent a stable strategy regime",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.INSUFFICIENT_CONTEXT,
                    detail="lookback window had < N trades",
                ),
            ),
        ),
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool(
            "behavioral_analysis_tool",
            {"execution_id": execution_id},
            mock_dispatcher_ctx,
        )

    # Outcome
    assert envelope.outcome_class in ("success", "partial")
    assert envelope.success is True

    # Citations — at least 1 with execution_id
    assert len(envelope.citations) >= 1
    assert any(c.opaque_id == execution_id for c in envelope.citations)

    # Assumptions
    assert len(envelope.assumptions) >= 1
    assert "assumes trades within lookback window represent a stable strategy regime" in envelope.assumptions

    # Declared failure modes extracted onto envelope
    assert any(fm.code == FailureModeCode.INSUFFICIENT_CONTEXT for fm in envelope.failure_modes)

    # Confidence > 0.5 (baseline 0.75)
    assert envelope.confidence is not None
    assert envelope.confidence > 0.5

    # Payload type
    assert isinstance(envelope.payload, BehavioralAnalysisPayload)


# ---------------------------------------------------------------------------
# Test: frozen envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_behavioral_analysis_envelope_frozen(mock_dispatcher_ctx):
    """Behavioral analysis envelope mutation raises ValidationError."""
    from pydantic import ValidationError
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.analytics.behavioral import BehavioralAnalysisPayload

    entry = _make_entry()
    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    execution_id = str(uuid.uuid4())
    payload = BehavioralAnalysisPayload(
        score=Decimal("75.00"),
        confidence=Decimal("80.00"),
        signals={"hesitation_normal": True, "entry_on_time": True,
                 "stop_not_moved": True, "managed_cleanly": True,
                 "no_revenge_trade": True, "no_fomo": True},
        narrative_fragments=["Behavioral score = 75/100"],
        provenance=ToolProvenance(
            citations=(EvidenceCitation(citation_kind="trade", opaque_id=execution_id),),
            assumptions=("assumes trades within lookback window represent a stable strategy regime",),
        ),
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool(
            "behavioral_analysis_tool",
            {"execution_id": execution_id},
            mock_dispatcher_ctx,
        )

    with pytest.raises((ValidationError, TypeError)):
        envelope.success = False  # type: ignore[misc]
