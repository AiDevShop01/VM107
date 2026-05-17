"""
Tests for envelope_writer journal_id persistence (Phase 47-02).
Phase 47.6-04: Updated for CapabilityProvenanceMixin — build_envelope now calls
stamp_at_write_time() which requires CapabilityRegistry. Tests patch CapabilityRegistry.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

_FAKE_HASH = "aabbccdd11223344"
_FAKE_TS = datetime(2026, 5, 17, tzinfo=timezone.utc)


def _make_fake_registry():
    fake_snapshot = MagicMock()
    fake_snapshot.snapshot_generated_at = _FAKE_TS
    fake_snapshot.snapshot_schema_version = "1.0"
    fake_reg = MagicMock()
    fake_reg.snapshot_hash = _FAKE_HASH
    fake_reg.snapshot = fake_snapshot
    return fake_reg


def test_write_with_journal_id():
    """build_envelope accepts journal_id kwarg and write_envelope persists it."""
    from core.agents.envelope_writer import build_envelope, write_envelope

    db = MagicMock()
    reg = _make_fake_registry()

    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg

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
    assert env.registry_snapshot_hash == _FAKE_HASH

    write_envelope(db, env)
    assert db["agent_envelopes"].insert_one.called

    call_args = db["agent_envelopes"].insert_one.call_args
    inserted_doc = call_args[0][0]
    assert inserted_doc["journal_id"] == "j1"


def test_write_without_journal_id():
    """build_envelope without journal_id kwarg results in journal_id None."""
    from core.agents.envelope_writer import build_envelope, write_envelope

    db = MagicMock()
    reg = _make_fake_registry()

    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg

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
