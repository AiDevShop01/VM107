"""
Tests for envelope_writer journal_id persistence (Phase 47-02).

Wave 0 xfail stub upgraded to GREEN in 47-02.
"""
from unittest.mock import MagicMock


def test_write_with_journal_id():
    """build_envelope accepts journal_id kwarg and write_envelope persists it."""
    from core.agents.envelope_writer import build_envelope, write_envelope

    db = MagicMock()

    env = build_envelope(
        task_id="t1",
        parent_task_id=None,
        agent_id="agent_zero",
        input_payload={},
        output_payload={},
        telemetry={"model_used": "gpt-4", "cost": {}, "reason_chain": []},
        status="success",
        source_envelope_id=None,
        journal_id="j1",
    )
    assert env.journal_id == "j1"

    write_envelope(db, env)
    assert db["agent_envelopes"].insert_one.called

    call_args = db["agent_envelopes"].insert_one.call_args
    inserted_doc = call_args[0][0]
    assert inserted_doc["journal_id"] == "j1"


def test_write_without_journal_id():
    """build_envelope without journal_id kwarg results in journal_id None."""
    from core.agents.envelope_writer import build_envelope, write_envelope

    db = MagicMock()

    env = build_envelope(
        task_id="t2",
        parent_task_id=None,
        agent_id="agent_zero",
        input_payload={},
        output_payload={},
        telemetry={"model_used": "gpt-4", "cost": {}, "reason_chain": []},
        status="success",
        source_envelope_id=None,
    )
    assert env.journal_id is None

    write_envelope(db, env)
    assert db["agent_envelopes"].insert_one.called

    call_args = db["agent_envelopes"].insert_one.call_args
    inserted_doc = call_args[0][0]
    assert inserted_doc["journal_id"] is None
