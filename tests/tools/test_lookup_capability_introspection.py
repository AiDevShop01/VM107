"""Tests for lookup_capability introspection log wiring.

Phase 47.6 Plan 06 Task 1 — TDD RED suite.

Verifies that every lookup/list call appends a CapabilityIntrospectionEvent
to the active AgentEnvelope via the envelope_context contextvar.

Critical invariant (B2 fix): introspecting a stub capability does NOT
write to capability_refusal_log. That log is ONLY written by tool_dispatcher
on attempted invocation. This file tests the introspection side ONLY.
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset CapabilityRegistry singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


@pytest.fixture
def real_registry(tmp_path):
    """Initialize a registry from the real VM107/registry root."""
    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = None


@pytest.fixture
def stub_registry(tmp_path):
    """Registry containing one stub capability and one real capability."""
    from core.registry.capability_registry import CapabilityRegistry
    import yaml

    registry_root = tmp_path / "registry"
    tool_dir = registry_root / "tool"
    tool_dir.mkdir(parents=True)

    (tool_dir / "some_real_tool.yaml").write_text(yaml.dump({
        "id": "some_real_tool",
        "type": "tool",
        "status": "real",
        "short_description": "A real tool",
        "long_description": "A fully implemented tool",
        "contracts": {"request": None, "response": None},
        "impact_on_decision": "LOW",
        "allowed_agent_profiles": ["agent_zero"],
        "dependencies": [],
        "related_capabilities": [],
        "deprecated": False,
        "tags": ["test"],
        "api_structure": "function",
        "location": {"source": "test", "planned_phase": None},
        "unblocks_when": [],
        "last_changed": "2026-05-17",
    }))

    (tool_dir / "some_stub_capability.yaml").write_text(yaml.dump({
        "id": "some_stub_capability",
        "type": "tool",
        "status": "stub",
        "short_description": "A stub tool",
        "long_description": "Not yet implemented",
        "contracts": {"request": None, "response": None},
        "impact_on_decision": "HIGH",
        "allowed_agent_profiles": ["agent_zero"],
        "dependencies": [],
        "related_capabilities": [],
        "deprecated": False,
        "tags": ["test"],
        "api_structure": "function",
        "location": {"source": "test", "planned_phase": "Phase 99"},
        "unblocks_when": [],
        "last_changed": "2026-05-17",
    }))

    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = None


@pytest.fixture
def fresh_envelope():
    """Build a minimal AgentEnvelope for testing introspection logging."""
    from core.contracts.envelope import AgentEnvelope

    return AgentEnvelope(
        task_id="test-task-001",
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
# Tests
# ---------------------------------------------------------------------------


def test_lookup_known_id_logs(real_registry, fresh_envelope):
    """lookup("get_trade_quality_score") inside envelope_context logs 1 introspection event."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context
    from fingpt_core.contracts.capability_registry import CapabilityIntrospectionEvent

    with envelope_context(fresh_envelope):
        result = lookup("get_trade_quality_score")

    assert result.status == "ok"
    assert len(fresh_envelope.capability_introspection_log) == 1

    event = fresh_envelope.capability_introspection_log[0]
    assert isinstance(event, CapabilityIntrospectionEvent)
    assert event.capability_id == "get_trade_quality_score"
    assert event.lookup_type == "lookup"
    assert event.returned_status == "real"


def test_lookup_unknown_id_logs(real_registry, fresh_envelope):
    """lookup("nonexistent") logs even when capability not found."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context
    from fingpt_core.contracts.capability_registry import CapabilityIntrospectionEvent

    with envelope_context(fresh_envelope):
        result = lookup("nonexistent_xyz_abc")

    assert result.status == "not_available"
    assert len(fresh_envelope.capability_introspection_log) == 1

    event = fresh_envelope.capability_introspection_log[0]
    assert isinstance(event, CapabilityIntrospectionEvent)
    assert event.capability_id == "nonexistent_xyz_abc"
    assert event.lookup_type == "lookup"
    # not_available means returned_status is None or "not_available"
    # (stub doesn't have a status to return)


def test_list_logs_filters(real_registry, fresh_envelope):
    """list_capabilities(tags=['behavioral']) logs lookup_type='list', capability_id=None."""
    from tools.lookup_capability import list_capabilities
    from core.agents.envelope_context import envelope_context
    from fingpt_core.contracts.capability_registry import CapabilityIntrospectionEvent

    with envelope_context(fresh_envelope):
        result = list_capabilities(tags=["behavioral"])

    assert len(fresh_envelope.capability_introspection_log) == 1

    event = fresh_envelope.capability_introspection_log[0]
    assert isinstance(event, CapabilityIntrospectionEvent)
    assert event.lookup_type == "list"
    assert event.capability_id is None
    assert event.filters is not None
    assert event.filters.get("tags") == ["behavioral"]
    assert event.returned_count == result.returned_count


def test_discovery_reason_passes_through(real_registry, fresh_envelope):
    """discovery_reason arg passes through to the introspection log entry."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context

    with envelope_context(fresh_envelope):
        lookup("get_trade_quality_score", discovery_reason="missing_param_understanding")

    assert len(fresh_envelope.capability_introspection_log) == 1
    event = fresh_envelope.capability_introspection_log[0]
    assert event.discovery_reason == "missing_param_understanding"


def test_log_carries_snapshot_hash(real_registry, fresh_envelope):
    """The introspection event carries registry_snapshot_hash matching the registry."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context
    from core.registry.capability_registry import CapabilityRegistry

    with envelope_context(fresh_envelope):
        lookup("get_trade_quality_score")

    reg = CapabilityRegistry.get()
    event = fresh_envelope.capability_introspection_log[0]
    assert event.registry_snapshot_hash == reg.snapshot_hash


def test_log_carries_occurred_at(real_registry, fresh_envelope):
    """The introspection event has a UTC timestamp."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context

    with envelope_context(fresh_envelope):
        lookup("get_trade_quality_score")

    event = fresh_envelope.capability_introspection_log[0]
    assert isinstance(event.occurred_at, datetime)
    assert event.occurred_at.tzinfo is not None


def test_outside_envelope_no_crash(real_registry):
    """Calling lookup() outside an envelope_context does NOT raise and does NOT log."""
    from tools.lookup_capability import lookup

    # No envelope_context active — should silently skip logging
    result = lookup("get_trade_quality_score")
    # No exception raised
    assert result.status == "ok"


def test_introspection_of_stub_does_NOT_trigger_refusal(stub_registry, fresh_envelope):
    """B2 fix: lookup("some_stub_capability") writes ONLY to capability_introspection_log.

    capability_refusal_log MUST remain empty after mere introspection of a stub.
    This is the critical regression-prevention test for the B2 architectural invariant.
    Introspection != invocation.
    """
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context

    with envelope_context(fresh_envelope):
        result = lookup("some_stub_capability")

    # Introspection log should have the event
    assert len(fresh_envelope.capability_introspection_log) == 1
    event = fresh_envelope.capability_introspection_log[0]
    assert event.capability_id == "some_stub_capability"
    assert event.returned_status == "stub"

    # Refusal log MUST be empty — introspection is not invocation (B2 fix)
    assert len(fresh_envelope.capability_refusal_log) == 0, (
        "B2 VIOLATION: capability_refusal_log must not be written by introspection. "
        "Refusal log is ONLY written by tool_dispatcher on invocation attempts."
    )
