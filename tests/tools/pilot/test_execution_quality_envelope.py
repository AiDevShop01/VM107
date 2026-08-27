"""Phase 70.5 Plan 06 Gate 1 — execution_quality RICH envelope unit test.

Tests validate:
- ExecutionQualityPayload (renamed from ExecutionQualityResult) + backward alias
- PAYLOAD_SCHEMA_VERSION = "1.0.0"
- ToolProvenance populated with trade + execution_id citations + assumption string
- confidence > 0.5 (baseline 0.80, complete evidence, deterministic)
- Envelope frozen

REQ-70.5-6 Gate 1 — execution_quality pilot.
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
    typical_confidence: float = 0.80,
    expected_freshness: int = 30,
    is_deterministic: bool = True,
    version: str = "1.0.0",
):
    from core.agents.tool_registry import ToolEntry
    return ToolEntry(
        id="execution_quality_tool",
        status="real",
        source_module="tools.execution_quality",
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=False,
    )


# ---------------------------------------------------------------------------
# Test: backward compat alias
# ---------------------------------------------------------------------------


def test_execution_quality_backward_compat_alias():
    """ExecutionQualityResult must remain importable (alias to ExecutionQualityPayload)."""
    from fingpt_core.contracts.analytics.execution_quality import (
        ExecutionQualityPayload,
        ExecutionQualityResult,
    )
    assert ExecutionQualityResult is ExecutionQualityPayload


def test_execution_quality_payload_schema_version():
    """ExecutionQualityPayload must have PAYLOAD_SCHEMA_VERSION = '1.0.0'."""
    from fingpt_core.contracts.analytics.execution_quality import ExecutionQualityPayload
    assert ExecutionQualityPayload.PAYLOAD_SCHEMA_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# Test: success path produces RICH provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_quality_success_envelope_rich(mock_dispatcher_ctx):
    """dispatch_tool('execution_quality_tool', ...) produces RICH envelope."""
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.analytics.execution_quality import ExecutionQualityPayload

    entry = _make_entry()
    execution_id = str(uuid.uuid4())

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    payload = ExecutionQualityPayload(
        score=Decimal("82.00"),
        confidence=Decimal("100.00"),
        signals={
            "entry_within_zone": True,
            "exit_at_target": True,
            "stop_respected": True,
            "r_target_achieved": True,
            "early_exit": False,
            "late_exit": False,
            "overextended_entry": False,
            "slippage_acceptable": True,
        },
        narrative_fragments=["Execution quality = 82/100"],
        provenance=ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=execution_id,
                    human_label=f"Execution {execution_id}",
                ),
                EvidenceCitation(
                    citation_kind="event",
                    opaque_id=f"fill_received:{execution_id}",
                    human_label="Fill received event",
                ),
            ),
            assumptions=(
                "assumes broker fill timestamps are server-authoritative (no client-clock skew)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM100 trades API timed out",
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
            "execution_quality_tool",
            {"execution_id": execution_id},
            mock_dispatcher_ctx,
        )

    # Outcome
    assert envelope.outcome_class in ("success", "partial")
    assert envelope.success is True

    # Citations — execution_id + fill event
    assert len(envelope.citations) >= 2
    assert any(c.opaque_id == execution_id for c in envelope.citations)

    # Assumptions
    assert len(envelope.assumptions) >= 1
    assert "assumes broker fill timestamps are server-authoritative (no client-clock skew)" in envelope.assumptions

    # Declared failure modes extracted
    assert any(fm.code == FailureModeCode.UPSTREAM_TIMEOUT for fm in envelope.failure_modes)

    # Confidence > 0.5 (baseline 0.80)
    assert envelope.confidence is not None
    assert envelope.confidence > 0.5

    # Payload type
    assert isinstance(envelope.payload, ExecutionQualityPayload)


# ---------------------------------------------------------------------------
# Test: frozen envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_quality_envelope_frozen(mock_dispatcher_ctx):
    """Execution quality envelope mutation raises ValidationError."""
    from pydantic import ValidationError
    from core.agents.tool_dispatcher import dispatch_tool
    from fingpt_core.contracts.analytics.execution_quality import ExecutionQualityPayload

    entry = _make_entry()
    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-test"
    mock_reg.lookup.return_value = None

    execution_id = str(uuid.uuid4())
    payload = ExecutionQualityPayload(
        score=Decimal("82.00"),
        confidence=Decimal("100.00"),
        signals={
            "entry_within_zone": True,
            "exit_at_target": True,
            "stop_respected": True,
            "r_target_achieved": True,
            "early_exit": False,
            "late_exit": False,
            "overextended_entry": False,
            "slippage_acceptable": True,
        },
        narrative_fragments=["Execution quality = 82/100"],
        provenance=ToolProvenance(
            citations=(EvidenceCitation(citation_kind="trade", opaque_id=execution_id),),
            assumptions=("assumes broker fill timestamps are server-authoritative (no client-clock skew)",),
        ),
    )

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool(
            "execution_quality_tool",
            {"execution_id": execution_id},
            mock_dispatcher_ctx,
        )

    with pytest.raises((ValidationError, TypeError)):
        envelope.success = False  # type: ignore[misc]
