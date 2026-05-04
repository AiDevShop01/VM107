"""
Wave 0 test scaffolding for AgentEnvelope journal_id field extension.

Tests in this file are xfail stubs. Downstream plan 47-02 removes the
xfail marker when it extends AgentEnvelope with `journal_id: str | None = None`.
"""
import pytest


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-02")
def test_journal_id_defaults_none():
    """An AgentEnvelope deserialized without journal_id has journal_id == None."""
    from core.contracts.envelope import AgentEnvelope
    # serialized without journal_id (existing Phase 44 docs)
    data = {
        "envelope_id": "env_test", "task_id": "t1", "parent_task_id": None,
        "agent_id": "agent_zero", "input": {}, "output": {}, "model_used": None,
        "cost": None, "reason_chain": None, "source_envelope_id": None,
        "schema_version": 1, "status": "success",
        "timestamp": "2026-05-04T00:00:00Z",
    }
    env = AgentEnvelope.model_validate(data)
    assert env.journal_id is None
