"""Phase 47.6-04 Task 1 — envelope_writer stamping tests.

Tests:
- test_stamping_at_write_time: stamp_at_write_time() sources hash from CapabilityRegistry.get()
  at call time, NOT cached at module init (Pitfall 9). Two patches → two different hashes.
- test_evaluation_runner_stamps_mode_b: _persist_envelope patches CapabilityRegistry to
  confirm snapshot_hash is captured at write time.
- test_init_does_not_capture_hash: instantiating EvaluationRunner-like object before
  CapabilityRegistry is initialized does NOT cache the hash.
- test_two_persists_different_hashes: L16 positive companion — single runner instance,
  two persists with different registry mocks, assert two distinct hashes in persisted docs.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

FAKE_HASH_A = "aabbccdd11223344aabbccdd11223344aabbccdd11223344aabbccdd11223344"
FAKE_HASH_B = "bbccddee22334455bbccddee22334455bbccddee22334455bbccddee22334455"
FAKE_TS = datetime(2026, 5, 17, tzinfo=timezone.utc)


def _make_fake_registry(snapshot_hash: str):
    """Build a fake CapabilityRegistry with controllable snapshot_hash."""
    fake_snapshot = MagicMock()
    fake_snapshot.snapshot_generated_at = FAKE_TS
    fake_snapshot.snapshot_schema_version = "1.0"

    fake_reg = MagicMock()
    fake_reg.snapshot_hash = snapshot_hash
    fake_reg.snapshot = fake_snapshot
    return fake_reg


def test_stamping_at_write_time_sources_fresh_hash():
    """stamp_at_write_time() reads CapabilityRegistry.get() at call time (Pitfall 9).

    Two consecutive calls with different patched registries must return different hashes.
    """
    from core.agents.envelope_writer import stamp_at_write_time

    reg_a = _make_fake_registry(FAKE_HASH_A)
    reg_b = _make_fake_registry(FAKE_HASH_B)

    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg_a
        stamp_a = stamp_at_write_time()

    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg_b
        stamp_b = stamp_at_write_time()

    assert stamp_a["registry_snapshot_hash"] == FAKE_HASH_A
    assert stamp_b["registry_snapshot_hash"] == FAKE_HASH_B
    # The two hashes must differ (proves write-time fetch)
    assert stamp_a["registry_snapshot_hash"] != stamp_b["registry_snapshot_hash"]


def test_stamp_at_write_time_returns_three_fields():
    """stamp_at_write_time() returns all 3 required provenance fields."""
    from core.agents.envelope_writer import stamp_at_write_time

    reg = _make_fake_registry(FAKE_HASH_A)
    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg
        stamp = stamp_at_write_time()

    assert set(stamp.keys()) == {
        "registry_snapshot_hash",
        "registry_snapshot_generated_at",
        "registry_schema_version",
    }
    assert stamp["registry_snapshot_hash"] == FAKE_HASH_A
    assert stamp["registry_snapshot_generated_at"] == FAKE_TS
    assert stamp["registry_schema_version"] == "1.0"


def test_evaluation_runner_stamps_mode_b():
    """_persist_envelope produces an envelope carrying the current snapshot_hash.

    Verified by patching CapabilityRegistry.get() to a known fake and inspecting
    the document inserted into the mock MongoDB collection.
    """
    import json

    reg = _make_fake_registry(FAKE_HASH_A)

    # Mock MongoDB collection to capture inserts
    inserted_docs = []
    mock_collection = MagicMock()
    mock_collection.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: mock_collection)

    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg

        from core.agents.evaluation_runner import _persist_envelope
        _persist_envelope(
            db=mock_db,
            task_id="task-1",
            journal_id="j-1",
            source_env_id=None,
            status="success",
            input_payload={"trigger": "test"},
            output_payload={"evaluation": {}},
        )

    assert len(inserted_docs) == 1
    doc = inserted_docs[0]
    assert doc["registry_snapshot_hash"] == FAKE_HASH_A


def test_init_does_not_capture_hash():
    """The evaluation runner does NOT capture registry_snapshot_hash at import/init time.

    Prove: patch CapabilityRegistry AFTER importing evaluation_runner. If hash were
    captured at module init, the patch would be too late and the test would fail.
    The test succeeds because the hash is only read at _persist_envelope() call time.
    """
    import importlib
    import core.agents.evaluation_runner  # ensure module is loaded

    reg = _make_fake_registry(FAKE_HASH_A)

    inserted_docs = []
    mock_collection = MagicMock()
    mock_collection.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: mock_collection)

    # Patch AFTER the module is already imported — proves lazy read
    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg

        from core.agents.evaluation_runner import _persist_envelope
        _persist_envelope(
            db=mock_db,
            task_id="task-neg",
            journal_id="j-neg",
            source_env_id=None,
            status="success",
            input_payload={},
            output_payload={},
        )

    assert len(inserted_docs) == 1
    # Hash was sourced from the RUNTIME patch, not from module-init time
    assert inserted_docs[0]["registry_snapshot_hash"] == FAKE_HASH_A


def test_two_persists_different_hashes():
    """L16 positive companion: one runner, two writes, two different hashes.

    Instantiate a single runner object (or call _persist_envelope twice).
    Patch CapabilityRegistry to return hash A; call _persist; patch to hash B;
    call _persist again. Assert docs carry A and B respectively.
    """
    reg_a = _make_fake_registry(FAKE_HASH_A)
    reg_b = _make_fake_registry(FAKE_HASH_B)

    inserted_docs = []
    mock_collection = MagicMock()
    mock_collection.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: mock_collection)

    from core.agents.evaluation_runner import _persist_envelope

    # First write — hash A
    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg_a
        _persist_envelope(
            db=mock_db,
            task_id="task-a",
            journal_id="j-a",
            source_env_id=None,
            status="success",
            input_payload={},
            output_payload={},
        )

    # Second write — hash B (snapshot changed mid-flight)
    with patch("core.agents.envelope_writer.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg_b
        _persist_envelope(
            db=mock_db,
            task_id="task-b",
            journal_id="j-b",
            source_env_id=None,
            status="success",
            input_payload={},
            output_payload={},
        )

    assert len(inserted_docs) == 2
    assert inserted_docs[0]["registry_snapshot_hash"] == FAKE_HASH_A
    assert inserted_docs[1]["registry_snapshot_hash"] == FAKE_HASH_B
