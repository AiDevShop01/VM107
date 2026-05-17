"""Phase 47.6-04 Task 1 — AgentEnvelope CapabilityProvenanceMixin composition tests.

Tests:
- test_required_field: building AgentEnvelope without registry_snapshot_hash raises ValidationError
- test_hash_too_short: registry_snapshot_hash < 8 chars raises
- test_hash_too_long: > 64 chars raises
- test_schema_version_bumped: default schema_version is 2 (RESEARCH Open Q5)
- test_legacy_reads_tolerated: read_envelope_tolerant() handles schema_version=1 docs
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pydantic

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


VALID_HASH = "a" * 8  # minimum valid length
VALID_TS = datetime(2026, 5, 17, tzinfo=timezone.utc)


def _make_envelope(**overrides):
    """Construct a minimal valid AgentEnvelope v2 including provenance fields."""
    from core.contracts.envelope import AgentEnvelope

    defaults = dict(
        task_id="t1",
        agent_id="agent_zero",
        input={"text": "test"},
        output={"result": "ok"},
        model_used="gpt-4o",
        cost={"tokens": 10, "cost_usd": 0.001, "latency_ms": 200},
        reason_chain=[],
        status="success",
        registry_snapshot_hash=VALID_HASH,
        registry_snapshot_generated_at=VALID_TS,
        registry_schema_version="1.0",
    )
    defaults.update(overrides)
    return AgentEnvelope(**defaults)


def test_required_field():
    """Building AgentEnvelope without registry_snapshot_hash raises ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        _make_envelope(registry_snapshot_hash=pydantic.fields.PydanticUndefined)


def test_required_field_missing_entirely():
    """Building AgentEnvelope without registry_snapshot_hash at all raises ValidationError."""
    from core.contracts.envelope import AgentEnvelope

    with pytest.raises(pydantic.ValidationError):
        AgentEnvelope(
            task_id="t1",
            agent_id="agent_zero",
            input={},
            output={},
            model_used="gpt-4o",
            cost={},
            reason_chain=[],
            status="success",
            registry_snapshot_generated_at=VALID_TS,
            # registry_snapshot_hash intentionally omitted
        )


def test_hash_too_short():
    """registry_snapshot_hash < 8 chars raises ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        _make_envelope(registry_snapshot_hash="abc")


def test_hash_too_long():
    """registry_snapshot_hash > 64 chars raises ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        _make_envelope(registry_snapshot_hash="x" * 65)


def test_schema_version_bumped():
    """AgentEnvelope.schema_version default is 2 (Phase 47.6 Q5 bump)."""
    from core.contracts.envelope import AgentEnvelope

    assert AgentEnvelope.model_fields["schema_version"].default == 2


def test_legacy_reads_tolerated():
    """read_envelope_tolerant() handles schema_version=1 doc without crashing."""
    from core.contracts.envelope import read_envelope_tolerant

    legacy_doc = {
        "task_id": "t1",
        "agent_id": "idea_agent",
        "input": {"text": "test"},
        "output": {"hypothesis": "x"},
        "model_used": "gpt-4",
        "cost": {},
        "reason_chain": [],
        "status": "success",
        "schema_version": 1,
        # No provenance fields — should be backfilled by tolerant reader
    }
    env = read_envelope_tolerant(legacy_doc)
    assert env is not None
    # Schema version is normalized to 2
    assert env.schema_version == 2
    # Provenance fields backfilled with sentinel
    from fingpt_core.contracts.capability_registry import REGISTRY_SNAPSHOT_PRE_47_6
    assert env.registry_snapshot_hash == REGISTRY_SNAPSHOT_PRE_47_6


def test_legacy_reads_do_not_mutate_input():
    """read_envelope_tolerant() does NOT mutate the input dict."""
    from core.contracts.envelope import read_envelope_tolerant

    legacy_doc = {
        "task_id": "t1",
        "agent_id": "idea_agent",
        "input": {},
        "output": {},
        "model_used": "gpt-4",
        "cost": {},
        "reason_chain": [],
        "status": "success",
        "schema_version": 1,
    }
    original_schema_version = legacy_doc["schema_version"]
    read_envelope_tolerant(legacy_doc)
    assert legacy_doc["schema_version"] == original_schema_version  # unchanged
