"""
Tests for AgentEnvelope journal_id field extension (Phase 47-02).

Wave 0 xfail stub upgraded to GREEN in 47-02.
"""
import pytest


def test_journal_id_defaults_none():
    """An AgentEnvelope deserialized without journal_id has journal_id == None."""
    from core.contracts.envelope import AgentEnvelope
    # serialized without journal_id (existing Phase 44 docs — backward compat)
    data = {
        "envelope_id": "env_test", "task_id": "t1", "parent_task_id": None,
        "agent_id": "agent_zero", "input": {}, "output": {}, "model_used": "gpt-4",
        "cost": {}, "reason_chain": [], "source_envelope_id": None,
        "schema_version": 1, "status": "success",
        "timestamp": "2026-05-04T00:00:00Z",
    }
    env = AgentEnvelope.model_validate(data)
    assert env.journal_id is None
    assert env.schema_version == 1


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
    )
    assert env.journal_id == "j1"
    assert env.schema_version == 1


def test_schema_version_unchanged():
    """schema_version stays at 1 after adding journal_id (additive optional field)."""
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
    )
    assert env.schema_version == 1
