"""Phase 47.6-04 Task 2 — PlannerOutput CapabilityProvenanceMixin stamping tests.

Tests:
- test_planner_output_has_provenance: write to planner_outputs Mongo includes 3 stamp fields
- test_planner_output_uses_mixin: PlannerOutput composes CapabilityProvenanceMixin
- test_planner_output_missing_hash_raises: building PlannerOutput without registry_snapshot_hash
  raises ValidationError (NOT NULL enforced at Pydantic layer)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pydantic

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

VALID_HASH = "aabbccdd11223344"
VALID_TS = datetime(2026, 5, 17, tzinfo=timezone.utc)


def _make_fake_registry(snapshot_hash: str = VALID_HASH):
    fake_snapshot = MagicMock()
    fake_snapshot.snapshot_generated_at = VALID_TS
    fake_snapshot.snapshot_schema_version = "1.0"
    fake_reg = MagicMock()
    fake_reg.snapshot_hash = snapshot_hash
    fake_reg.snapshot = fake_snapshot
    return fake_reg


def test_planner_output_uses_mixin():
    """PlannerOutput composes CapabilityProvenanceMixin."""
    from core.agents.planner_output import PlannerOutput
    from fingpt_core.provenance import CapabilityProvenanceMixin

    assert issubclass(PlannerOutput, CapabilityProvenanceMixin)


def test_planner_output_missing_hash_raises():
    """Building PlannerOutput without registry_snapshot_hash raises ValidationError."""
    from core.agents.planner_output import PlannerOutput

    with pytest.raises(pydantic.ValidationError):
        PlannerOutput(
            task_id="t1",
            agent_id="agent_zero",
            plan_steps=[],
            registry_snapshot_generated_at=VALID_TS,
            # registry_snapshot_hash intentionally omitted
        )


def test_planner_output_has_provenance():
    """write_planner_output() inserts doc with 3 provenance fields into planner_outputs."""
    from core.agents.planner_output import PlannerOutput, write_planner_output

    inserted_docs = []
    mock_collection = MagicMock()
    mock_collection.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: mock_collection)

    reg = _make_fake_registry()
    with patch("core.agents.planner_output.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg
        write_planner_output(
            db=mock_db,
            task_id="t1",
            agent_id="agent_zero",
            plan_steps=["step-A", "step-B"],
        )

    assert len(inserted_docs) == 1
    doc = inserted_docs[0]
    assert doc["registry_snapshot_hash"] == VALID_HASH
    assert "registry_snapshot_generated_at" in doc
    assert "registry_schema_version" in doc


def test_planner_output_write_time_stamping():
    """write_planner_output() stamps at write time, not init time (Pitfall 9)."""
    from core.agents.planner_output import write_planner_output

    HASH_A = "a" * 16
    HASH_B = "b" * 16
    reg_a = _make_fake_registry(HASH_A)
    reg_b = _make_fake_registry(HASH_B)

    inserted_docs = []
    mock_collection = MagicMock()
    mock_collection.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=lambda name: mock_collection)

    with patch("core.agents.planner_output.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg_a
        write_planner_output(db=mock_db, task_id="t-a", agent_id="agent_zero", plan_steps=[])

    with patch("core.agents.planner_output.CapabilityRegistry") as mock_cls:
        mock_cls.get.return_value = reg_b
        write_planner_output(db=mock_db, task_id="t-b", agent_id="agent_zero", plan_steps=[])

    assert len(inserted_docs) == 2
    assert inserted_docs[0]["registry_snapshot_hash"] == HASH_A
    assert inserted_docs[1]["registry_snapshot_hash"] == HASH_B
