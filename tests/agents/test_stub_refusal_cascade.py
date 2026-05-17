"""Tests for stub/experimental refusal cascade.

Phase 47.6 Plan 06 Task 2 — TDD RED suite.

Verifies:
- tool_dispatcher refuses stub/experimental capabilities on INVOCATION
- CapabilityRefusalEvent appended to envelope.capability_refusal_log
- Correct auto_confidence_adjustment magnitudes (HIGH=-15, MEDIUM=-10, LOW=-5)
- Phase 47.3 ConfidenceAdjustment rows produced by _emit_capability_unavailable_adjustments
- real/deprecated capabilities are NOT refused
- The cascade reads from capability_refusal_log ONLY (B2 fix)
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_summary(capability_id, status, impact):
    """Build a CapabilitySummary for testing."""
    from fingpt_core.contracts.capability_registry import (
        CapabilitySummary, CapabilityStatus, CapabilityType, ImpactLevel,
    )
    return CapabilitySummary(
        id=capability_id,
        type=CapabilityType.TOOL,
        status=CapabilityStatus(status),
        short_description=f"Test {status} tool",
        long_description=f"A {status} capability for testing",
        contracts={"request": None, "response": None},
        impact_on_decision=ImpactLevel(impact),
        allowed_agent_profiles=("agent_zero",),
        dependencies=(),
        related_capabilities=(),
        deprecated=False,
        tags=("test",),
        api_structure="function",
        location={"source": "test", "planned_phase": "Phase 99"},
        unblocks_when=(),
        last_changed="2026-05-17",
    )


def _make_envelope():
    """Build a minimal AgentEnvelope for testing."""
    from core.contracts.envelope import AgentEnvelope
    return AgentEnvelope(
        task_id="test-task",
        agent_id="agent_zero",
        input={},
        output={},
        model_used="gpt-4",
        cost={},
        reason_chain=[],
        status="success",
        registry_snapshot_hash="a" * 64,
        registry_snapshot_generated_at=datetime.now(tz=timezone.utc),
        registry_schema_version="1.0",
    )


# ---------------------------------------------------------------------------
# should_refuse tests
# ---------------------------------------------------------------------------


def test_should_refuse_stub():
    """should_refuse returns True for stub capabilities."""
    from core.agents.refusal_cascade import should_refuse
    summary = _make_summary("test_stub", "stub", "HIGH")
    assert should_refuse(summary) is True


def test_should_refuse_experimental():
    """should_refuse returns True for experimental capabilities (V1 lock LD-6c)."""
    from core.agents.refusal_cascade import should_refuse
    summary = _make_summary("test_exp", "experimental", "HIGH")
    assert should_refuse(summary) is True


def test_should_not_refuse_real():
    """should_refuse returns False for real capabilities."""
    from core.agents.refusal_cascade import should_refuse
    summary = _make_summary("test_real", "real", "HIGH")
    assert should_refuse(summary) is False


def test_should_not_refuse_deprecated():
    """should_refuse returns False for deprecated capabilities (invokable per LD-6c)."""
    from core.agents.refusal_cascade import should_refuse
    summary = _make_summary("test_dep", "deprecated", "HIGH")
    assert should_refuse(summary) is False


# ---------------------------------------------------------------------------
# build_refusal_payload shape tests
# ---------------------------------------------------------------------------


def test_build_refusal_payload_stub_high():
    """Refusal payload for stub HIGH has auto_confidence_adjustment=-15."""
    from core.agents.refusal_cascade import build_refusal_payload
    summary = _make_summary("some_stub", "stub", "HIGH")
    payload = build_refusal_payload(summary)

    assert payload["status"] == "capability_unavailable"
    assert payload["capability_id"] == "some_stub"
    assert payload["registry_status"] == "stub"
    assert payload["auto_confidence_adjustment"] == -15
    assert payload["impact_on_reasoning"] == "partial_context_loss"


def test_build_refusal_payload_stub_medium():
    """Refusal payload for stub MEDIUM has auto_confidence_adjustment=-10."""
    from core.agents.refusal_cascade import build_refusal_payload
    summary = _make_summary("some_stub", "stub", "MEDIUM")
    payload = build_refusal_payload(summary)
    assert payload["auto_confidence_adjustment"] == -10


def test_build_refusal_payload_stub_low():
    """Refusal payload for stub LOW has auto_confidence_adjustment=-5."""
    from core.agents.refusal_cascade import build_refusal_payload
    summary = _make_summary("some_stub", "stub", "LOW")
    payload = build_refusal_payload(summary)
    assert payload["auto_confidence_adjustment"] == -5


def test_build_refusal_payload_experimental():
    """Experimental capabilities get identical refusal treatment (V1 lock LD-6c)."""
    from core.agents.refusal_cascade import build_refusal_payload
    summary = _make_summary("some_exp", "experimental", "HIGH")
    payload = build_refusal_payload(summary)
    assert payload["status"] == "capability_unavailable"
    assert payload["registry_status"] == "experimental"
    assert payload["auto_confidence_adjustment"] == -15


# ---------------------------------------------------------------------------
# tool_dispatcher invocation gate tests
# ---------------------------------------------------------------------------


def test_stub_high_impact_invocation(monkeypatch):
    """Invoking a stub HIGH capability via dispatcher triggers refusal + appends RefusalEvent."""
    from core.agents.tool_dispatcher import dispatch_tool, UnknownToolError
    from core.agents.envelope_context import envelope_context
    from fingpt_core.contracts.capability_registry import CapabilityRefusalEvent
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    stub_summary = _make_summary("some_stub_tool", "stub", "HIGH")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = stub_summary
    mock_reg.snapshot_hash = "b" * 64

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with envelope_context(envelope):
        result = dispatch_tool("some_stub_tool", {})

    # Should return refusal payload, NOT invoke the tool
    assert result["status"] == "capability_unavailable"
    assert result["capability_id"] == "some_stub_tool"
    assert result["registry_status"] == "stub"
    assert result["auto_confidence_adjustment"] == -15

    # Refusal event appended to envelope.capability_refusal_log (B2 — invocation)
    assert len(envelope.capability_refusal_log) == 1
    event = envelope.capability_refusal_log[0]
    assert isinstance(event, CapabilityRefusalEvent)
    assert event.capability_id == "some_stub_tool"
    assert event.auto_confidence_adjustment == -15

    # Introspection log untouched (dispatch doesn't introspect)
    assert len(envelope.capability_introspection_log) == 0


def test_stub_medium_impact_invocation(monkeypatch):
    """Invoking stub MEDIUM → auto_confidence_adjustment=-10."""
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_context import envelope_context
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    stub_summary = _make_summary("medium_stub", "stub", "MEDIUM")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = stub_summary
    mock_reg.snapshot_hash = "c" * 64

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with envelope_context(envelope):
        result = dispatch_tool("medium_stub", {})

    assert result["auto_confidence_adjustment"] == -10
    assert len(envelope.capability_refusal_log) == 1
    assert envelope.capability_refusal_log[0].auto_confidence_adjustment == -10


def test_stub_low_impact_invocation(monkeypatch):
    """Invoking stub LOW → auto_confidence_adjustment=-5."""
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_context import envelope_context
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    stub_summary = _make_summary("low_stub", "stub", "LOW")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = stub_summary
    mock_reg.snapshot_hash = "d" * 64

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with envelope_context(envelope):
        result = dispatch_tool("low_stub", {})

    assert result["auto_confidence_adjustment"] == -5


def test_experimental_invocation_refused(monkeypatch):
    """Experimental capability is hard-refused identically to stub (V1 lock LD-6c)."""
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_context import envelope_context
    from fingpt_core.contracts.capability_registry import CapabilityRefusalEvent
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    exp_summary = _make_summary("exp_capability", "experimental", "HIGH")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = exp_summary
    mock_reg.snapshot_hash = "e" * 64

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with envelope_context(envelope):
        result = dispatch_tool("exp_capability", {})

    assert result["status"] == "capability_unavailable"
    assert result["registry_status"] == "experimental"
    assert len(envelope.capability_refusal_log) == 1
    assert isinstance(envelope.capability_refusal_log[0], CapabilityRefusalEvent)


def test_real_capability_invokable(monkeypatch):
    """Real capability is NOT refused — invoked normally, NO refusal log entry."""
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_context import envelope_context
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    real_summary = _make_summary("real_tool", "real", "HIGH")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = real_summary
    mock_reg.snapshot_hash = "f" * 64

    # Mock the tool implementation
    mock_impl = MagicMock(return_value={"result": "success"})

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with patch("core.agents.tool_dispatcher._invoke_tool_impl", mock_impl):
        with envelope_context(envelope):
            result = dispatch_tool("real_tool", {"arg": "value"})

    assert result == {"result": "success"}
    assert len(envelope.capability_refusal_log) == 0


def test_phase_47_3_cascade_reads_refusal_log(monkeypatch):
    """Refusal during evaluation produces ConfidenceAdjustment from refusal_log.

    Tests _emit_capability_unavailable_adjustments reads capability_refusal_log
    NOT capability_introspection_log (B2 fix).
    """
    from core.agents.refusal_cascade import _emit_capability_unavailable_adjustments
    from fingpt_core.contracts.capability_registry import CapabilityRefusalEvent

    envelope = _make_envelope()

    # Add a refusal event (as if dispatch_tool was called)
    refusal_event = CapabilityRefusalEvent(
        capability_id="some_stub_tool",
        registry_status="stub",
        impact_on_decision="HIGH",
        planned_phase="Phase 99",
        impact_on_reasoning="partial_context_loss",
        auto_confidence_adjustment=-15,
        registry_snapshot_hash="a" * 64,
        occurred_at=datetime.now(tz=timezone.utc),
        reasoning_context_id="test-envelope-id",
    )
    envelope.capability_refusal_log.append(refusal_event)

    # Call the cascade function
    adjustments = _emit_capability_unavailable_adjustments(envelope)

    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.reason == "capability_unavailable:some_stub_tool"
    assert adj.capability_id == "some_stub_tool"
    assert adj.impact == -15
