"""
Phase 44 AgentEnvelope schema tests.

Covers:
- All 11 required fields present with auto-generated envelope_id and timestamp
- schema_version default of 1
- parent_task_id and source_envelope_id default to None
- status Literal validation (success/failure/degraded only)
- validate_envelope_schema_version helper — pass and raise cases
- model_dump() produces all fields with UUID string envelope_id
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
import pydantic

from core.contracts.envelope import AgentEnvelope, validate_envelope_schema_version
from core.contracts.exceptions import SchemaVersionMismatchError


def _make_envelope(**overrides) -> AgentEnvelope:
    """Create a minimal valid AgentEnvelope with optional field overrides."""
    defaults = dict(
        task_id="t1",
        agent_id="idea_agent",
        input={"text": "build a momentum strategy"},
        output={"hypothesis": "momentum holds"},
        model_used="deepseek/deepseek-v4-flash",
        cost={"tokens": 100, "cost_usd": 0.001, "latency_ms": 500},
        reason_chain=["affinity_match", "peak_soft"],
        status="success",
    )
    defaults.update(overrides)
    return AgentEnvelope(**defaults)


def test_envelope_creation_minimal():
    """
    Minimal valid envelope succeeds; auto-generated fields are present.
    parent_task_id and source_envelope_id default to None.
    schema_version defaults to 1.
    """
    env = _make_envelope()
    # Auto-generated fields
    assert env.envelope_id is not None
    assert len(env.envelope_id) == 36  # UUID4 string
    assert env.timestamp is not None
    # Defaults
    assert env.parent_task_id is None
    assert env.source_envelope_id is None
    assert env.schema_version == 1
    # Explicit fields
    assert env.task_id == "t1"
    assert env.agent_id == "idea_agent"
    assert env.status == "success"


@pytest.mark.parametrize("bad_status", ["invalid_status", "pending", "ok", "", "SUCCESS"])
def test_envelope_invalid_status_raises(bad_status):
    """AgentEnvelope rejects invalid status values; only success/failure/degraded allowed."""
    with pytest.raises(pydantic.ValidationError):
        _make_envelope(status=bad_status)


@pytest.mark.parametrize("valid_status", ["success", "failure", "degraded"])
def test_envelope_valid_statuses(valid_status):
    """All three valid status values are accepted."""
    env = _make_envelope(status=valid_status)
    assert env.status == valid_status


def test_validate_envelope_schema_version_pass():
    """validate_envelope_schema_version returns envelope unchanged when versions match."""
    env = _make_envelope()
    result = validate_envelope_schema_version(env, expected=1)
    assert result is env


def test_schema_version_mismatch():
    """validate_envelope_schema_version raises SchemaVersionMismatchError on mismatch."""
    # Manually build a v2 envelope (schema_version=2 instead of default 1)
    env_v2 = _make_envelope(schema_version=2)
    with pytest.raises(SchemaVersionMismatchError) as exc_info:
        validate_envelope_schema_version(env_v2, expected=1)
    err = exc_info.value
    assert err.expected == 1
    assert err.received == 2


def test_envelope_model_dump_all_fields():
    """model_dump() produces dict with all 11 fields and UUID string envelope_id."""
    env = _make_envelope()
    d = env.model_dump()
    required_keys = {
        "envelope_id", "task_id", "parent_task_id", "agent_id",
        "input", "output", "model_used", "cost", "reason_chain",
        "source_envelope_id", "schema_version", "status", "timestamp",
    }
    assert required_keys <= set(d.keys())
    # envelope_id is a UUID string (36 chars, 4 hyphens)
    assert isinstance(d["envelope_id"], str)
    assert len(d["envelope_id"]) == 36
    assert d["envelope_id"].count("-") == 4
