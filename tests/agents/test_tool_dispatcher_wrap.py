"""Phase 70.5 Plan 03 — TDD RED tests for tool_dispatcher.py refactor.

Tests cover:
- Happy path: dispatch_tool returns ToolResultEnvelope[T], outcome_class="success"
- Stub refusal: outcome_class="refused", CapabilityRefusalEvent written to agent envelope
- Confidence-refusal: confidence < 0.3 flips outcome_class="refused" + cascade writes
- Failure path: resolver exception → outcome_class="failure", typed FailureMode
- Frozen result: envelope mutation raises ValidationError
- Provenance extraction: payload.provenance.citations / assumptions / declared_failure_modes
  are extracted onto the envelope (Critical Gate 2 prerequisite)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.invocation_context import InvocationContext, MAX_EXECUTION_DEPTH
from fingpt_core.contracts.tool_envelope import (
    ENVELOPE_SCHEMA_VERSION,
    ToolConfidenceSignals,
    ToolProvenance,
    ToolResultEnvelope,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _DummyPayload(BaseModel):
    """Minimal typed payload for test assertions."""
    model_config = ConfigDict(frozen=True)
    value: str = "test"
    PAYLOAD_SCHEMA_VERSION: str = "1.0"


class _DummyPayloadWithProvenance(BaseModel):
    """Payload with a populated ToolProvenance field (RICH wrap)."""
    model_config = ConfigDict(frozen=True)
    value: str = "rich"
    PAYLOAD_SCHEMA_VERSION: str = "1.0"
    provenance: ToolProvenance = ToolProvenance(
        signals=ToolConfidenceSignals(evidence_quality="complete"),
        citations=(
            EvidenceCitation(citation_kind="trade", opaque_id="t1", human_label="Trade 1"),
            EvidenceCitation(citation_kind="event", opaque_id="e1"),
        ),
        assumptions=("assumes timezone is account timezone", "assumes no fills missed"),
        declared_failure_modes=(
            FailureMode(code=FailureModeCode.UPSTREAM_TIMEOUT, detail="declared timeout risk"),
        ),
    )


def _make_ctx(
    depth: int = 0,
    parent_id: uuid.UUID | None = None,
    trace_id: uuid.UUID | None = None,
) -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=parent_id,
        trace_id=trace_id or uuid.uuid4(),
        agent_id="test_agent",
        conversation_id="conv-abc",
        execution_depth=depth,
    )


def _make_mock_entry(
    tool_id: str = "test_tool",
    status: str = "real",
    typical_confidence: float = 0.85,
    expected_freshness_seconds: int = 60,
    is_deterministic: bool = False,
    version: str = "1.0",
    source_module: str | None = "tools.test_tool",
    is_facade: bool = False,
) -> MagicMock:
    """Build a mock ToolEntry mirroring tool_registry.ToolEntry structure."""
    entry = MagicMock()
    entry.id = tool_id
    entry.status = status
    entry.typical_confidence = typical_confidence
    entry.expected_freshness_seconds = expected_freshness_seconds
    entry.is_deterministic = is_deterministic
    entry.version = version
    entry.source_module = source_module
    entry.is_facade = is_facade
    return entry


def _make_mock_summary(
    tool_id: str = "test_tool",
    status_value: str = "stub",
    impact_value: str = "HIGH",
    snapshot_hash: str = "snap456",
) -> MagicMock:
    """Build a mock CapabilitySummary for registry lookups."""
    summary = MagicMock()
    summary.id = tool_id
    summary.status = MagicMock()
    summary.status.value = status_value
    summary.impact_on_decision = MagicMock()
    summary.impact_on_decision.value = impact_value
    summary.location = {"planned_phase": "71"}
    return summary


def _make_mock_registry(snapshot_hash: str = "snap123") -> MagicMock:
    """Build a mock CapabilityRegistry."""
    reg = MagicMock()
    reg.snapshot_hash = snapshot_hash
    return reg


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


class TestDispatchToolHappyPath:
    """dispatch_tool succeeds → ToolResultEnvelope[T] with outcome_class='success'."""

    @pytest.mark.asyncio
    async def test_returns_tool_result_envelope(self):
        """dispatch_tool returns a ToolResultEnvelope on the happy path."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()
        mock_summary = MagicMock()
        mock_summary.id = "test_tool"
        mock_summary.status = MagicMock()
        mock_summary.status.value = "real"
        mock_summary.impact_on_decision = MagicMock()
        mock_summary.impact_on_decision.value = "LOW"
        mock_summary.location = {}

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert isinstance(result, ToolResultEnvelope)

    @pytest.mark.asyncio
    async def test_outcome_class_success(self):
        """Happy path produces outcome_class='success' and success=True."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.outcome_class == "success"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_confidence_is_positive(self):
        """Happy path envelope has positive confidence (baseline 0.85, evidence_quality=complete)."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry(typical_confidence=0.85)
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.confidence is not None
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_registry_snapshot_hash_on_envelope(self):
        """registry_snapshot_hash on the envelope matches mock reg.snapshot_hash."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry(snapshot_hash="deadbeef1234")

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.registry_snapshot_hash == "deadbeef1234"

    @pytest.mark.asyncio
    async def test_telemetry_called_on_success(self):
        """emit_envelope_log is called exactly once on the happy path."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log") as mock_telemetry,
        ):
            await dispatch_tool("test_tool", {}, ctx)

        mock_telemetry.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — stub refusal
# ---------------------------------------------------------------------------


class TestDispatchToolStubRefusal:
    """Stub/experimental refusal → refused envelope + CapabilityRefusalEvent preserved."""

    @pytest.mark.asyncio
    async def test_stub_produces_refused_envelope(self):
        """Stub capability refusal produces outcome_class='refused'."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry(status="stub")
        mock_summary = _make_mock_summary(status_value="stub")
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=True),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._lookup_summary", return_value=mock_summary),
            patch("core.agents.tool_dispatcher.build_refusal_payload", return_value={"status": "capability_unavailable"}),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.outcome_class == "refused"
        assert result.success is False

    @pytest.mark.asyncio
    async def test_stub_refusal_reason_populated(self):
        """Stub refusal populates refusal_reason with 'capability_unavailable'."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry(status="stub")
        mock_summary = _make_mock_summary(status_value="stub")
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=True),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._lookup_summary", return_value=mock_summary),
            patch("core.agents.tool_dispatcher.build_refusal_payload", return_value={"status": "capability_unavailable"}),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.refusal_reason is not None
        assert "capability_unavailable" in result.refusal_reason

    @pytest.mark.asyncio
    async def test_capability_refusal_event_written_on_stub(self):
        """CapabilityRefusalEvent is appended to current_envelope.capability_refusal_log."""
        from core.agents.tool_dispatcher import dispatch_tool
        from core.agents.envelope_context import envelope_context

        ctx = _make_ctx()
        mock_entry = _make_mock_entry(status="stub")
        mock_summary = _make_mock_summary(status_value="stub")
        mock_reg = _make_mock_registry()

        # Create a mock agent envelope with a capability_refusal_log
        mock_agent_envelope = MagicMock()
        mock_agent_envelope.capability_refusal_log = []
        mock_agent_envelope.envelope_id = uuid.uuid4()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=True),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._lookup_summary", return_value=mock_summary),
            patch("core.agents.tool_dispatcher.build_refusal_payload", return_value={"status": "capability_unavailable"}),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            with envelope_context(mock_agent_envelope):
                result = await dispatch_tool("test_tool", {}, ctx)

        # CapabilityRefusalEvent must have been appended
        assert len(mock_agent_envelope.capability_refusal_log) == 1


# ---------------------------------------------------------------------------
# Tests — confidence refusal (< 0.3)
# ---------------------------------------------------------------------------


class TestDispatchToolConfidenceRefusal:
    """Confidence < 0.3 flips to refused + writes CapabilityRefusalEvent cascade."""

    @pytest.mark.asyncio
    async def test_low_confidence_flips_to_refused(self):
        """When computed confidence < 0.3, outcome_class flips to 'refused'."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        # baseline=0.5, evidence_quality="none" → 0.5 * 0.2 = 0.1 < 0.3
        mock_entry = _make_mock_entry(typical_confidence=0.5, is_deterministic=False)

        class _LowConfPayload(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: str = "low"
            PAYLOAD_SCHEMA_VERSION: str = "1.0"
            provenance: ToolProvenance = ToolProvenance(
                signals=ToolConfidenceSignals(evidence_quality="none"),
            )

        mock_payload = _LowConfPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.outcome_class == "refused"
        assert result.success is False
        assert result.refusal_reason is not None
        assert "confidence_below_threshold" in result.refusal_reason

    @pytest.mark.asyncio
    async def test_confidence_refusal_writes_capability_refusal_event(self):
        """Confidence-refusal path appends CapabilityRefusalEvent to agent envelope (Pitfall 8)."""
        from core.agents.tool_dispatcher import dispatch_tool
        from core.agents.envelope_context import envelope_context

        ctx = _make_ctx()
        mock_entry = _make_mock_entry(typical_confidence=0.5, is_deterministic=False)

        class _LowConf2Payload(BaseModel):
            model_config = ConfigDict(frozen=True)
            value: str = "low2"
            PAYLOAD_SCHEMA_VERSION: str = "1.0"
            provenance: ToolProvenance = ToolProvenance(
                signals=ToolConfidenceSignals(evidence_quality="none"),
            )

        mock_payload = _LowConf2Payload()
        mock_reg = _make_mock_registry()
        mock_agent_envelope = MagicMock()
        mock_agent_envelope.capability_refusal_log = []
        mock_agent_envelope.envelope_id = uuid.uuid4()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            with envelope_context(mock_agent_envelope):
                result = await dispatch_tool("test_tool", {}, ctx)

        assert result.outcome_class == "refused"
        # CapabilityRefusalEvent must have been appended (Pitfall 8 cascade)
        assert len(mock_agent_envelope.capability_refusal_log) >= 1


# ---------------------------------------------------------------------------
# Tests — failure path
# ---------------------------------------------------------------------------


class TestDispatchToolFailurePath:
    """Resolver exception → failure envelope with typed FailureMode."""

    @pytest.mark.asyncio
    async def test_timeout_produces_failure_envelope(self):
        """TimeoutError from resolver → outcome_class='failure', FailureModeCode.UPSTREAM_TIMEOUT."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(side_effect=TimeoutError("timed out"))),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.outcome_class == "failure"
        assert result.success is False
        assert len(result.failure_modes) == 1
        assert result.failure_modes[0].code == FailureModeCode.UPSTREAM_TIMEOUT

    @pytest.mark.asyncio
    async def test_failure_mode_detail_contains_exception_text(self):
        """FailureMode.detail contains the exception message."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(side_effect=TimeoutError("connection timed out after 30s"))),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert "connection timed out after 30s" in result.failure_modes[0].detail

    @pytest.mark.asyncio
    async def test_telemetry_called_on_failure(self):
        """emit_envelope_log is called even on failure path."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(side_effect=TimeoutError("timeout"))),
            patch("core.agents.tool_dispatcher.emit_envelope_log") as mock_tel,
        ):
            await dispatch_tool("test_tool", {}, ctx)

        mock_tel.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — frozen envelope
# ---------------------------------------------------------------------------


class TestEnvelopeFrozen:
    """Returned envelope is immutable (Phase 60 Append-Only doctrine)."""

    @pytest.mark.asyncio
    async def test_envelope_mutation_raises(self):
        """Attempting to set a field on the returned envelope raises ValidationError."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        with pytest.raises((ValidationError, TypeError)):
            result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests — provenance extraction (Critical Gate 2)
# ---------------------------------------------------------------------------


class TestProvenanceExtraction:
    """payload.provenance.citations/assumptions/declared_failure_modes extracted onto envelope."""

    @pytest.mark.asyncio
    async def test_citations_extracted_from_provenance(self):
        """2 EvidenceCitations in payload.provenance → envelope.citations has 2 entries."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayloadWithProvenance()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert len(result.citations) == 2

    @pytest.mark.asyncio
    async def test_assumptions_extracted_from_provenance(self):
        """2 assumption strings in payload.provenance → envelope.assumptions has 2 entries."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayloadWithProvenance()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert len(result.assumptions) == 2

    @pytest.mark.asyncio
    async def test_declared_failure_modes_extracted_from_provenance(self):
        """1 declared FailureMode in payload.provenance → appears in envelope.failure_modes."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayloadWithProvenance()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert any(
            fm.code == FailureModeCode.UPSTREAM_TIMEOUT
            for fm in result.failure_modes
        )

    @pytest.mark.asyncio
    async def test_no_provenance_field_yields_empty_citations(self):
        """payload with no .provenance field → envelope.citations is empty tuple."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx()
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()  # no provenance field
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.citations == ()
        assert result.assumptions == ()


# ---------------------------------------------------------------------------
# Tests — UnknownToolError preserved
# ---------------------------------------------------------------------------


class TestUnknownToolError:
    """UnknownToolError is raised for unregistered tools."""

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self):
        """dispatch_tool raises UnknownToolError for unregistered tool."""
        from core.agents.tool_dispatcher import UnknownToolError, dispatch_tool

        ctx = _make_ctx()
        mock_reg = _make_mock_registry()
        mock_reg.lookup = MagicMock(return_value=None)

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher._get_tool_entry", side_effect=KeyError("no_such_tool")),
        ):
            with pytest.raises(UnknownToolError):
                await dispatch_tool("no_such_tool", {}, ctx)
