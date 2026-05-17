"""
Tests for AgentEnvelope journal_id field extension (Phase 47-02).
Phase 47.6-04: Updated for CapabilityProvenanceMixin required fields.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

_VALID_HASH = "aabbccdd11223344"
_VALID_TS = datetime(2026, 5, 17, tzinfo=timezone.utc)


def _provenance_fields():
    """Return the 3 required provenance fields for test EnvelopeEnvelope creation."""
    return {
        "registry_snapshot_hash": _VALID_HASH,
        "registry_snapshot_generated_at": _VALID_TS,
        "registry_schema_version": "1.0",
    }


def test_journal_id_defaults_none():
    """An AgentEnvelope deserialized with schema_version=2 (v2) has journal_id=None."""
    from core.contracts.envelope import AgentEnvelope
    # schema_version=2 (Phase 47.6) with provenance fields
    data = {
        "envelope_id": "env_test", "task_id": "t1", "parent_task_id": None,
        "agent_id": "agent_zero", "input": {}, "output": {}, "model_used": "gpt-4",
        "cost": {}, "reason_chain": [], "source_envelope_id": None,
        "schema_version": 2, "status": "success",
        "timestamp": "2026-05-04T00:00:00Z",
        **_provenance_fields(),
    }
    env = AgentEnvelope.model_validate(data)
    assert env.journal_id is None
    assert env.schema_version == 2


def test_journal_id_set_on_construction():
    """AgentEnvelope constructed with journal_id stores it correctly."""
    from core.contracts.envelope import AgentEnvelope
    env = AgentEnvelope(
        task_id="t1",
        parent_task_id=None,
        agent_id="agent_zero",
        input={},
        output={},
        model_used="gpt-4",
        cost={},
        reason_chain=[],
        source_envelope_id=None,
        status="success",
        journal_id="j1",
        **_provenance_fields(),
    )
    assert env.journal_id == "j1"
    assert env.schema_version == 2  # Phase 47.6 bump


def test_schema_version_default_is_two():
    """schema_version defaults to 2 in Phase 47.6 (RESEARCH Open Q5 bump from 1)."""
    from core.contracts.envelope import AgentEnvelope
    env = AgentEnvelope(
        task_id="t1",
        parent_task_id=None,
        agent_id="agent_zero",
        input={},
        output={},
        model_used="gpt-4",
        cost={},
        reason_chain=[],
        status="success",
        **_provenance_fields(),
    )
    assert env.schema_version == 2
