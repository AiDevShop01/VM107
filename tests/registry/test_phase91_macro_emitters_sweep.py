"""Phase 91 Plan 2 — capability registry sweep for macro indicator emitters.

Asserts the 3 Plan 2 registry YAMLs (2 event_type + 1 agent_profile) exist,
parse, validate against the Phase 47.6 _BaseEntrySchema, carry all required
Phase 47.6 fields, and cross-reference each other consistently.

REQ-91-10: Capability Registry sweep finds the macro emitter agent_profile
and the 2 event_type entries (release_alert, macro_indicator_threshold_alert).
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest
import yaml


_VM107_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

REGISTRY_ROOT = _VM107_ROOT / "registry"

EVENT_TYPE_RELEASE_ALERT = REGISTRY_ROOT / "event_type" / "release_alert.yaml"
EVENT_TYPE_THRESHOLD_ALERT = REGISTRY_ROOT / "event_type" / "macro_indicator_threshold_alert.yaml"
AGENT_PROFILE_EMITTER = REGISTRY_ROOT / "agent_profile" / "vm107.macro_indicator_alert_emitter.yaml"

ALL_PLAN_2_YAMLS = [
    EVENT_TYPE_RELEASE_ALERT,
    EVENT_TYPE_THRESHOLD_ALERT,
    AGENT_PROFILE_EMITTER,
]


def _load(path: pathlib.Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


# ── Existence + parse ────────────────────────────────────────────────────────

def test_all_three_yamls_exist():
    missing = [p for p in ALL_PLAN_2_YAMLS if not p.exists()]
    assert not missing, f"Plan 2 must ship 3 registry YAMLs; missing: {missing}"


def test_all_three_yamls_parse():
    for path in ALL_PLAN_2_YAMLS:
        data = _load(path)
        assert isinstance(data, dict), f"{path} did not parse to dict"
        assert "id" in data and "type" in data, f"{path} missing id/type"


# ── Phase 47.6 _BaseEntrySchema validation ───────────────────────────────────

def test_all_three_yamls_validate_against_base_entry_schema():
    """Each entry passes the per-type Pydantic schema validator (Stage 2)."""
    from core.registry.validation import _BaseEntrySchema  # type: ignore[attr-defined]

    for path in ALL_PLAN_2_YAMLS:
        data = _load(path)
        # Will raise pydantic.ValidationError on missing/wrong-typed required fields
        validated = _BaseEntrySchema.model_validate(data)
        assert validated.id == data["id"]
        assert validated.type.value == data["type"]


# ── Phase 47.6 required fields ───────────────────────────────────────────────

REQUIRED_FIELDS = {
    "id",
    "type",
    "status",
    "last_changed",
    "impact_on_decision",
    "phase",
}


def test_release_alert_has_phase_47_6_required_fields():
    data = _load(EVENT_TYPE_RELEASE_ALERT)
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"release_alert.yaml missing required fields: {missing}"
    assert data["status"] == "real"
    assert data["phase"] == 91
    assert data["type"] == "event_type"
    assert data["impact_on_decision"] in ("HIGH", "MEDIUM", "LOW")


def test_threshold_alert_has_phase_47_6_required_fields():
    data = _load(EVENT_TYPE_THRESHOLD_ALERT)
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"macro_indicator_threshold_alert.yaml missing required fields: {missing}"
    assert data["status"] == "real"
    assert data["phase"] == 91
    assert data["type"] == "event_type"
    # Threshold alerts are direct trader-visible → HIGH
    assert data["impact_on_decision"] == "HIGH"


def test_emitter_profile_has_phase_47_6_required_fields():
    data = _load(AGENT_PROFILE_EMITTER)
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"vm107.macro_indicator_alert_emitter.yaml missing required fields: {missing}"
    assert data["status"] == "real"
    assert data["phase"] == 91
    assert data["type"] == "agent_profile"
    # Emitter is HIGH (its emits become trader-visible alerts)
    assert data["impact_on_decision"] == "HIGH"


# ── Cross-references between the 3 entries ────────────────────────────────────

def test_emitter_declares_both_event_types_in_emits():
    """Agent profile lists both event types it produces."""
    data = _load(AGENT_PROFILE_EMITTER)
    emits = set(data.get("emits") or [])
    assert "release_alert" in emits
    assert "macro_indicator_threshold_alert" in emits


def test_event_types_declare_emitter_as_producer():
    for path in (EVENT_TYPE_RELEASE_ALERT, EVENT_TYPE_THRESHOLD_ALERT):
        data = _load(path)
        producers = data.get("producers") or []
        assert "vm107.macro_indicator_alert_emitter" in producers, (
            f"{path.name} must list vm107.macro_indicator_alert_emitter as producer"
        )


def test_event_types_declare_uae_as_consumer():
    for path in (EVENT_TYPE_RELEASE_ALERT, EVENT_TYPE_THRESHOLD_ALERT):
        data = _load(path)
        consumers = data.get("consumers") or []
        # universal_alert_engine is the UAE on VM100
        assert any("universal_alert_engine" in c or "phase91" in c for c in consumers), (
            f"{path.name} must consume into Phase 91 UAE; got consumers={consumers}"
        )


# ── Phase 70.5 envelope-provenance fields on the emitter agent_profile ───────

def test_emitter_profile_has_envelope_provenance_fields():
    """Phase 70.5 — typical_confidence + expected_freshness_seconds +
    is_deterministic + version must be populated on the emitter profile."""
    data = _load(AGENT_PROFILE_EMITTER)
    for field in ("typical_confidence", "expected_freshness_seconds",
                  "is_deterministic", "version"):
        assert field in data, f"emitter profile missing Phase 70.5 field: {field}"


# ── Schema versions ──────────────────────────────────────────────────────────

def test_event_types_carry_schema_version_1_0():
    """Plan 2 ships against the v1.0 alert_candidate envelope schema."""
    for path in (EVENT_TYPE_RELEASE_ALERT, EVENT_TYPE_THRESHOLD_ALERT):
        data = _load(path)
        assert str(data.get("schema_version")) == "1.0", (
            f"{path.name} schema_version must be 1.0 to match Plan 1 envelope"
        )
