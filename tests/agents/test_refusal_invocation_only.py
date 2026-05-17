"""Tests for B2 fix: refusal cascade fires ONLY on invocation, NOT introspection.

Phase 47.6 Plan 06 Task 2 — TDD RED suite.

These tests are the critical regression-prevention suite for the B2 architectural
invariant: "agent attempts to INVOKE the capability" triggers refusal, NOT
"agent introspects the capability via lookup()".

CONTEXT.md decision #6c explicit lock:
- capability_introspection_log: every lookup()/list() call — NO confidence penalty
- capability_refusal_log: ONLY invocation attempts — confidence penalty fires

Proves:
1. lookup("stub_id") → introspection_log has 1 entry, refusal_log EMPTY
2. lookup("stub_id") THEN dispatch_tool("stub_id") → introspection=1, refusal=1, adjustments=1
3. 3 dispatch attempts on same stub → 3 refusal entries → 3 ConfidenceAdjustment rows
4. list_capabilities(status="stub") → introspection_log gets 1 entry, refusal_log EMPTY
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


def _make_summary(capability_id, status="stub", impact="HIGH"):
    from fingpt_core.contracts.capability_registry import (
        CapabilitySummary, CapabilityStatus, CapabilityType, ImpactLevel,
    )
    return CapabilitySummary(
        id=capability_id,
        type=CapabilityType.TOOL,
        status=CapabilityStatus(status),
        short_description=f"Test {status}",
        long_description=f"Test {status} capability",
        contracts={"request": None, "response": None},
        impact_on_decision=ImpactLevel(impact),
        allowed_agent_profiles=(),
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


@pytest.fixture(autouse=True)
def reset_registry():
    from core.registry.capability_registry import CapabilityRegistry
    original = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original


@pytest.fixture
def real_registry():
    from core.registry.capability_registry import CapabilityRegistry
    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = None


# ---------------------------------------------------------------------------
# B2 separation tests
# ---------------------------------------------------------------------------


def test_introspection_of_stub_no_cascade(real_registry):
    """Critical B2 test: lookup("stub") → introspection_log=1, refusal_log=0, adjustments=0.

    This is the regression-prevention test. lookup() is introspection, not invocation.
    Introspecting a stub does NOT penalize confidence.
    """
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context
    from core.agents.refusal_cascade import _emit_capability_unavailable_adjustments

    envelope = _make_envelope()
    stub_summary = _make_summary("stub_tool_id", "stub", "HIGH")

    with patch.object(real_registry, "lookup", return_value=stub_summary):
        with envelope_context(envelope):
            lookup("stub_tool_id")

    # Introspection happened
    assert len(envelope.capability_introspection_log) == 1
    assert envelope.capability_introspection_log[0].capability_id == "stub_tool_id"

    # Refusal log EMPTY — introspection is NOT invocation (B2 fix)
    assert len(envelope.capability_refusal_log) == 0, (
        "B2 VIOLATION: introspecting a stub must NOT write to capability_refusal_log"
    )

    # ConfidenceAdjustment cascade: ZERO rows (refusal_log is empty)
    adjustments = _emit_capability_unavailable_adjustments(envelope)
    assert len(adjustments) == 0, (
        "B2 VIOLATION: cascade reads refusal_log; no invocations = no adjustments"
    )


def test_introspection_then_invocation_produces_one_cascade(real_registry, monkeypatch):
    """lookup() + dispatch_tool() → introspection=1, refusal=1, adjustments=1.

    This proves the cascade counts invocations, not introspections.
    """
    from tools.lookup_capability import lookup
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_context import envelope_context
    from core.agents.refusal_cascade import _emit_capability_unavailable_adjustments
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    stub_summary = _make_summary("stub_tool_id", "stub", "HIGH")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = stub_summary
    mock_reg.snapshot_hash = "x" * 64

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with envelope_context(envelope):
        # Step 1: INTROSPECT (lookup — no refusal)
        lookup("stub_tool_id")
        # Step 2: INVOKE (dispatch_tool — refusal fires)
        dispatch_tool("stub_tool_id", {})

    # Introspection log has 1 entry (from lookup)
    assert len(envelope.capability_introspection_log) == 1

    # Refusal log has exactly 1 entry (from dispatch_tool only)
    assert len(envelope.capability_refusal_log) == 1, (
        "Exactly 1 refusal: the invocation attempt (NOT double-counted with introspection)"
    )

    # ConfidenceAdjustment: exactly 1 row
    adjustments = _emit_capability_unavailable_adjustments(envelope)
    assert len(adjustments) == 1


def test_multiple_invocation_attempts_each_cascade(monkeypatch):
    """3 dispatch attempts on same stub → 3 refusal entries → 3 ConfidenceAdjustment rows."""
    from core.agents.tool_dispatcher import dispatch_tool
    from core.agents.envelope_context import envelope_context
    from core.agents.refusal_cascade import _emit_capability_unavailable_adjustments
    from core.registry.capability_registry import CapabilityRegistry

    envelope = _make_envelope()
    stub_summary = _make_summary("stub_tool_id", "stub", "HIGH")

    mock_reg = MagicMock()
    mock_reg.lookup.return_value = stub_summary
    mock_reg.snapshot_hash = "y" * 64

    monkeypatch.setattr(CapabilityRegistry, "get", staticmethod(lambda: mock_reg))

    with envelope_context(envelope):
        dispatch_tool("stub_tool_id", {})
        dispatch_tool("stub_tool_id", {})
        dispatch_tool("stub_tool_id", {})

    assert len(envelope.capability_refusal_log) == 3

    adjustments = _emit_capability_unavailable_adjustments(envelope)
    assert len(adjustments) == 3


def test_list_call_no_refusal(real_registry):
    """list_capabilities(status='stub') returns stubs, writes to introspection_log, NOT refusal_log."""
    from tools.lookup_capability import list_capabilities
    from core.agents.envelope_context import envelope_context
    from core.agents.refusal_cascade import _emit_capability_unavailable_adjustments

    envelope = _make_envelope()

    with envelope_context(envelope):
        result = list_capabilities(status="stub")

    # Introspection log gets 1 list-type entry
    assert len(envelope.capability_introspection_log) == 1
    assert envelope.capability_introspection_log[0].lookup_type == "list"

    # Refusal log EMPTY — listing stubs is NOT invoking them (B2 fix)
    assert len(envelope.capability_refusal_log) == 0

    # No cascade adjustments
    adjustments = _emit_capability_unavailable_adjustments(envelope)
    assert len(adjustments) == 0
