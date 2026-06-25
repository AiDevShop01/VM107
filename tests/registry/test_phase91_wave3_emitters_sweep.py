"""Phase 91 Plan 3 Task 2 — Wave 3 capability registry sweep.

Asserts the 5 Plan 3 registry YAMLs (4 event_type + 1 agent_profile) exist,
parse, validate against the Phase 47.6 _BaseEntrySchema, carry all required
Phase 47.6 fields, and cross-reference each other consistently.

REQ-91-10: Capability Registry sweep finds:
  - 4 event_type entries: regime_change_alert, correlation_break_alert,
    liquidity_stress_alert, discovery_alert
  - 1 agent_profile entry: vm107.macro_liquidity_monitor
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

EVENT_TYPE_REGIME_CHANGE = REGISTRY_ROOT / "event_type" / "regime_change_alert.yaml"
EVENT_TYPE_CORRELATION_BREAK = REGISTRY_ROOT / "event_type" / "correlation_break_alert.yaml"
EVENT_TYPE_LIQUIDITY_STRESS = REGISTRY_ROOT / "event_type" / "liquidity_stress_alert.yaml"
EVENT_TYPE_DISCOVERY = REGISTRY_ROOT / "event_type" / "discovery_alert.yaml"
AGENT_PROFILE_LIQUIDITY = REGISTRY_ROOT / "agent_profile" / "vm107.macro_liquidity_monitor.yaml"

ALL_PLAN_3_YAMLS = [
    EVENT_TYPE_REGIME_CHANGE,
    EVENT_TYPE_CORRELATION_BREAK,
    EVENT_TYPE_LIQUIDITY_STRESS,
    EVENT_TYPE_DISCOVERY,
    AGENT_PROFILE_LIQUIDITY,
]


def _load(path: pathlib.Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


# ── Existence + parse ────────────────────────────────────────────────────────

def test_all_five_yamls_exist():
    missing = [p for p in ALL_PLAN_3_YAMLS if not p.exists()]
    assert not missing, f"Plan 3 must ship 5 registry YAMLs; missing: {missing}"


def test_all_five_yamls_parse():
    for path in ALL_PLAN_3_YAMLS:
        data = _load(path)
        assert isinstance(data, dict), f"{path} did not parse to dict"
        assert "id" in data and "type" in data, f"{path} missing id/type"


# ── Phase 47.6 _BaseEntrySchema validation ───────────────────────────────────

def test_all_five_yamls_validate_against_base_entry_schema():
    from core.registry.validation import _BaseEntrySchema  # type: ignore[attr-defined]

    for path in ALL_PLAN_3_YAMLS:
        data = _load(path)
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


@pytest.mark.parametrize("path", [
    EVENT_TYPE_REGIME_CHANGE,
    EVENT_TYPE_CORRELATION_BREAK,
    EVENT_TYPE_LIQUIDITY_STRESS,
    EVENT_TYPE_DISCOVERY,
])
def test_event_type_yamls_have_phase_47_6_required_fields(path):
    data = _load(path)
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"{path.name} missing required fields: {missing}"
    assert data["type"] == "event_type"
    assert data["phase"] == 91
    # Phase 47.6 _BaseEntrySchema enforces HIGH/MEDIUM/LOW enum
    assert data["impact_on_decision"] in ("HIGH", "MEDIUM", "LOW")


def test_liquidity_monitor_profile_has_phase_47_6_required_fields():
    data = _load(AGENT_PROFILE_LIQUIDITY)
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"vm107.macro_liquidity_monitor.yaml missing: {missing}"
    assert data["type"] == "agent_profile"
    assert data["phase"] == 91
    # Status experimental until Phase 86 substrate fully ships (per plan)
    assert data["status"] in ("experimental", "real")


# ── Impact_on_decision per alert type ───────────────────────────────────────


def test_regime_change_alert_impact_high():
    data = _load(EVENT_TYPE_REGIME_CHANGE)
    assert data["impact_on_decision"] == "HIGH"


def test_correlation_break_alert_impact_high():
    data = _load(EVENT_TYPE_CORRELATION_BREAK)
    assert data["impact_on_decision"] == "HIGH"


def test_liquidity_stress_alert_impact_high():
    data = _load(EVENT_TYPE_LIQUIDITY_STRESS)
    # HIGH per Phase 47.6 _BaseEntrySchema enum — top tier; the actual
    # alert severity ('Critical' on the envelope) carries P1 routing.
    assert data["impact_on_decision"] == "HIGH"


def test_discovery_alert_impact_medium():
    data = _load(EVENT_TYPE_DISCOVERY)
    # MEDIUM per LD-91-8 — informational, not deterministic
    assert data["impact_on_decision"] == "MEDIUM"


# ── Cross-references ─────────────────────────────────────────────────────────


def test_regime_change_alert_lists_macro_regime_monitor_as_producer():
    data = _load(EVENT_TYPE_REGIME_CHANGE)
    producers = data.get("producers") or []
    assert "vm107.macro_regime_monitor" in producers


def test_correlation_break_alert_lists_macro_relationship_discovery_as_producer():
    data = _load(EVENT_TYPE_CORRELATION_BREAK)
    producers = data.get("producers") or []
    assert "vm107.macro_relationship_discovery" in producers


def test_liquidity_stress_alert_lists_macro_liquidity_monitor_as_producer():
    data = _load(EVENT_TYPE_LIQUIDITY_STRESS)
    producers = data.get("producers") or []
    assert "vm107.macro_liquidity_monitor" in producers


def test_discovery_alert_lists_macro_relationship_discovery_as_producer():
    data = _load(EVENT_TYPE_DISCOVERY)
    producers = data.get("producers") or []
    assert "vm107.macro_relationship_discovery" in producers


def test_event_types_declare_uae_as_consumer():
    for path in (
        EVENT_TYPE_REGIME_CHANGE,
        EVENT_TYPE_CORRELATION_BREAK,
        EVENT_TYPE_LIQUIDITY_STRESS,
        EVENT_TYPE_DISCOVERY,
    ):
        data = _load(path)
        consumers = data.get("consumers") or []
        assert any(
            "universal_alert_engine" in c or "phase91" in c for c in consumers
        ), f"{path.name} must consume into Phase 91 UAE; got {consumers}"


def test_liquidity_monitor_profile_lists_liquidity_stress_alert_in_emits():
    data = _load(AGENT_PROFILE_LIQUIDITY)
    emits = set(data.get("emits") or [])
    assert "liquidity_stress_alert" in emits


# ── Phase 70.5 envelope-provenance fields on the new agent_profile ──────────


def test_liquidity_monitor_profile_has_envelope_provenance_fields():
    data = _load(AGENT_PROFILE_LIQUIDITY)
    for field in (
        "typical_confidence",
        "expected_freshness_seconds",
        "is_deterministic",
        "version",
    ):
        assert field in data, f"liquidity monitor profile missing Phase 70.5: {field}"
