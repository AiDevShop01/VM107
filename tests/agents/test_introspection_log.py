"""Tests for AgentEnvelope introspection log append-only semantics.

Phase 47.6 Plan 06 Task 1 — TDD RED suite.

Verifies:
- Log is append-only (3 calls → 3 entries; first entry unchanged after subsequent calls)
- Log entries are frozen (immutable after creation)
- Log persists across Mongo round-trip (write → read)
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

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
def real_registry():
    """Initialize a registry from the real VM107/registry root."""
    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = None


@pytest.fixture
def fresh_envelope():
    """Build a minimal AgentEnvelope for testing."""
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


def test_log_append_only(real_registry, fresh_envelope):
    """3 consecutive lookup() calls produce 3 entries; first entry unmodified after subsequent calls."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context

    with envelope_context(fresh_envelope):
        lookup("get_trade_quality_score")
        lookup("lookup_capability")
        lookup("get_trade_quality_score")

    log = fresh_envelope.capability_introspection_log
    assert len(log) == 3

    # First entry preserved after 2 subsequent lookups
    first_entry = log[0]
    assert first_entry.capability_id == "get_trade_quality_score"
    assert first_entry.lookup_type == "lookup"

    # Each entry has its own occurred_at (distinct timestamps possible)
    # All entries are separate objects
    assert log[0] is not log[1]
    assert log[1] is not log[2]


def test_log_persists_across_writes(real_registry, fresh_envelope):
    """After 2 lookups the envelope's introspection log survives model_dump/re-read."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context
    from core.contracts.envelope import read_envelope_tolerant

    with envelope_context(fresh_envelope):
        lookup("get_trade_quality_score")
        lookup("lookup_capability")

    # Simulate Mongo round-trip: model_dump → reconstruct
    doc = fresh_envelope.model_dump(mode="json")
    doc["_id"] = fresh_envelope.envelope_id

    # Remove _id for re-construction (AgentEnvelope doesn't have _id field)
    doc_without_id = {k: v for k, v in doc.items() if k != "_id"}
    # Use schema_version=2 path
    doc_without_id["schema_version"] = 2
    rehydrated = read_envelope_tolerant(doc_without_id)

    assert len(rehydrated.capability_introspection_log) == 2
    assert rehydrated.capability_introspection_log[0].capability_id == "get_trade_quality_score"
    assert rehydrated.capability_introspection_log[1].capability_id == "lookup_capability"


def test_log_entry_is_frozen_event(real_registry, fresh_envelope):
    """Attempting to mutate a logged CapabilityIntrospectionEvent raises (frozen=True)."""
    from tools.lookup_capability import lookup
    from core.agents.envelope_context import envelope_context
    from pydantic import ValidationError

    with envelope_context(fresh_envelope):
        lookup("get_trade_quality_score")

    event = fresh_envelope.capability_introspection_log[0]

    # frozen=True means attribute assignment raises
    with pytest.raises((TypeError, ValidationError)):
        event.capability_id = "mutated_id"
