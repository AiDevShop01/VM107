"""Phase 91 Plan 1 — capability registry sweep for Universal Alert Engine.

Asserts the universal_alert_engine.yaml contract entry exists at the
canonical path and passes the Phase 47.6 schema requirements:
  - id, type, status, last_changed, impact_on_decision, phase, hard_scoped

Also re-asserts alert_candidate_created.yaml is promoted to real / v1.0.

REQ-91-10: Capability Registry sweep finds the UAE contract YAML.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

VM107_ROOT = pathlib.Path(__file__).resolve().parents[2]
UAE_CONTRACT_YAML = VM107_ROOT / "registry" / "contract" / "universal_alert_engine.yaml"
ALERT_CANDIDATE_EVENT_YAML = VM107_ROOT / "registry" / "event_type" / "alert_candidate_created.yaml"
ALERT_CANDIDATE_SCHEMA_JSON = VM107_ROOT / "tests" / "phase89" / "fixtures" / "alert_candidate_event.schema.json"


def test_universal_alert_engine_yaml_exists():
    assert UAE_CONTRACT_YAML.exists(), (
        f"REQ-91-10 violated: {UAE_CONTRACT_YAML} not found. "
        "Phase 91 Plan 1 Task 1 must ship the UAE contract YAML."
    )


def test_universal_alert_engine_yaml_loads():
    data = yaml.safe_load(UAE_CONTRACT_YAML.read_text())
    assert isinstance(data, dict)
    assert data["id"] == "universal_alert_engine"
    assert data["type"] == "contract"


def test_universal_alert_engine_yaml_has_phase_47_6_required_fields():
    data = yaml.safe_load(UAE_CONTRACT_YAML.read_text())
    required = ["id", "type", "status", "last_changed", "impact_on_decision", "phase", "hard_scoped"]
    missing = [f for f in required if f not in data]
    assert not missing, f"UAE contract YAML missing Phase 47.6 required fields: {missing}"
    assert data["status"] == "real"
    assert data["phase"] == 91
    assert data["impact_on_decision"] in ("HIGH", "MEDIUM", "LOW")
    assert data["hard_scoped"] is True


def test_universal_alert_engine_yaml_declares_dsl_operators():
    """REQ-91-3 — closed DSL operator set is registered in the contract."""
    data = yaml.safe_load(UAE_CONTRACT_YAML.read_text())
    ops = data.get("dsl_operators", {})
    assert "leaf" in ops and "compound" in ops
    leaf = set(ops["leaf"])
    expected_leaf = {"greater_than", "less_than", "crosses_above", "crosses_below", "percentile", "surprise"}
    assert leaf >= expected_leaf, f"DSL leaf ops missing: {expected_leaf - leaf}"
    assert "all" in ops["compound"] and "any" in ops["compound"]


def test_universal_alert_engine_yaml_declares_alert_types():
    """REQ-91-3 / LD-91-3 — 7-type taxonomy registered."""
    data = yaml.safe_load(UAE_CONTRACT_YAML.read_text())
    types = set(data.get("alert_types", []))
    expected = {"price", "macro_indicator", "regime", "correlation", "liquidity", "economic_release", "discovery"}
    assert types >= expected, f"alert_types missing: {expected - types}"


def test_universal_alert_engine_yaml_declares_lifecycle_fsm():
    """LD-91-6 — lifecycle FSM registered with expired as terminal."""
    data = yaml.safe_load(UAE_CONTRACT_YAML.read_text())
    fsm = data.get("lifecycle_fsm", {})
    assert "created" in fsm and "active" in fsm and "expired" in fsm
    assert fsm["expired"] == []  # terminal


def test_alert_candidate_created_yaml_promoted_to_real():
    """REQ-91-10 — schema promotion from experimental → real."""
    data = yaml.safe_load(ALERT_CANDIDATE_EVENT_YAML.read_text())
    assert data["status"] == "real", (
        f"alert_candidate_created.yaml status is {data['status']!r}; "
        "Phase 91 Plan 1 promotes to 'real'."
    )
    assert str(data["schema_version"]) == "1.0"


def test_alert_candidate_event_schema_v1_has_event_id_required():
    """Schema v1.0 — event_id is required for idempotency."""
    import json
    schema = json.loads(ALERT_CANDIDATE_SCHEMA_JSON.read_text())
    assert "event_id" in schema["required"]
    assert schema["properties"]["schema_version"]["const"] == "1.0"
