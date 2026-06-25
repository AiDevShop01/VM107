"""Phase 91 Plan 6 Task 2 — Wave 6 capability registry sweep.

Asserts the 2 Plan 6 registry YAMLs (1 notification_channel + 1 agent_profile)
exist, parse, validate against Phase 47.6 _BaseEntrySchema, carry required
fields, and cross-reference each other consistently.

REQ-91-10: Capability Registry sweep finds:
  - 1 notification_channel entry: agent_webhook
  - 1 agent_profile entry: vm107.macro_review_agent
  - Final Phase 91 tally (across all 6 plans): ≥11 entries

Plan 6 closes REQ-91-10 by landing the final 2 YAMLs needed for full coverage.
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

NOTIFICATION_CHANNEL_AGENT_WEBHOOK = REGISTRY_ROOT / "notification_channel" / "agent_webhook.yaml"
AGENT_PROFILE_MACRO_REVIEW = REGISTRY_ROOT / "agent_profile" / "vm107.macro_review_agent.yaml"

ALL_PLAN_6_YAMLS = [
    NOTIFICATION_CHANNEL_AGENT_WEBHOOK,
    AGENT_PROFILE_MACRO_REVIEW,
]


def _load(path: pathlib.Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


# ── Existence + parse ────────────────────────────────────────────────────────


def test_all_two_yamls_exist():
    missing = [p for p in ALL_PLAN_6_YAMLS if not p.exists()]
    assert not missing, f"Plan 6 must ship 2 registry YAMLs; missing: {missing}"


def test_all_two_yamls_parse():
    for path in ALL_PLAN_6_YAMLS:
        data = _load(path)
        assert isinstance(data, dict), f"{path} did not parse to dict"
        assert "id" in data and "type" in data, f"{path} missing id/type"


# ── Phase 47.6 _BaseEntrySchema validation ───────────────────────────────────


def test_all_two_yamls_validate_against_base_entry_schema():
    from core.registry.validation import _BaseEntrySchema  # type: ignore[attr-defined]

    for path in ALL_PLAN_6_YAMLS:
        data = _load(path)
        validated = _BaseEntrySchema.model_validate(data)
        assert validated.id == data["id"]
        assert validated.type.value == data["type"]


# ── Phase 47.6 required fields ──────────────────────────────────────────────


REQUIRED_FIELDS = {
    "id",
    "type",
    "status",
    "last_changed",
    "impact_on_decision",
    "phase",
}


@pytest.mark.parametrize("path", ALL_PLAN_6_YAMLS)
def test_yamls_have_phase_47_6_required_fields(path):
    data = _load(path)
    missing = REQUIRED_FIELDS - set(data.keys())
    assert not missing, f"{path.name} missing required fields: {missing}"
    assert data["phase"] == 91
    assert data["impact_on_decision"] in ("HIGH", "MEDIUM", "LOW")


def test_agent_webhook_is_notification_channel():
    data = _load(NOTIFICATION_CHANNEL_AGENT_WEBHOOK)
    assert data["type"] == "notification_channel"
    assert data["id"] == "agent_webhook"
    assert data["impact_on_decision"] == "HIGH"


def test_macro_review_agent_is_agent_profile():
    data = _load(AGENT_PROFILE_MACRO_REVIEW)
    assert data["type"] == "agent_profile"
    assert data["id"] == "vm107.macro_review_agent"
    assert data["impact_on_decision"] == "HIGH"


# ── REQ-91-9 self-loop ban — denied_dispatch_targets includes self ──────────


def test_macro_review_agent_denied_dispatch_targets_includes_self():
    """REQ-91-9 — macro_review_agent.yaml denies macro_review_agent as a target.

    Contract-level self-loop prevention; defense in depth alongside VM100's
    loop_safety_guard MAX_AGENT_CHAIN_DEPTH=3.
    """
    data = _load(AGENT_PROFILE_MACRO_REVIEW)
    denied = data.get("denied_dispatch_targets") or []
    assert "macro_review_agent" in denied or "vm107.macro_review_agent" in denied, (
        f"denied_dispatch_targets must ban macro_review_agent as a target; "
        f"got: {denied}"
    )


def test_macro_review_agent_does_not_emit_self_loop_alert_types():
    """emits MUST NOT include liquidity_stress_alert or regime_change_alert.

    Those would re-trigger macro_review_agent via the AGENT_DISPATCH_TABLE.
    """
    data = _load(AGENT_PROFILE_MACRO_REVIEW)
    emits = set(data.get("emits") or [])
    assert "liquidity_stress_alert" not in emits, (
        f"macro_review_agent must NOT emit liquidity_stress_alert (self-loop)"
    )
    assert "regime_change_alert" not in emits, (
        f"macro_review_agent must NOT emit regime_change_alert (self-loop)"
    )


# ── Phase 70.5 envelope-provenance fields on agent_profile ──────────────────


def test_macro_review_agent_profile_has_envelope_provenance_fields():
    data = _load(AGENT_PROFILE_MACRO_REVIEW)
    for field in (
        "typical_confidence",
        "expected_freshness_seconds",
        "is_deterministic",
        "version",
    ):
        assert field in data, f"macro_review_agent profile missing Phase 70.5: {field}"


# ── Cross-VM contract referenced ────────────────────────────────────────────


def test_macro_review_agent_profile_references_cross_vm_contract():
    data = _load(AGENT_PROFILE_MACRO_REVIEW)
    assert data.get("cross_vm_contract") == "vm107.macro_review_agent.invoke"


def test_agent_webhook_channel_references_cross_vm_contract():
    data = _load(NOTIFICATION_CHANNEL_AGENT_WEBHOOK)
    assert data.get("cross_vm_contract") == "vm107.macro_review_agent.invoke"


# ── Final Phase 91 registry tally ───────────────────────────────────────────


def test_phase_91_total_registry_count_at_least_eleven():
    """REQ-91-10 — final Phase 91 registry tally across all 6 plans is ≥11.

    Expected entries by type:
      - 1 contract: universal_alert_engine (Plan 1)
      - ≥5 event_type: macro_indicator_threshold_alert (Plan 2),
        regime_change_alert + correlation_break_alert + liquidity_stress_alert
        + discovery_alert (Plan 3), release_alert (Plan 2)
      - ≥3 agent_profile: macro_indicator_alert_emitter (Plan 2),
        vm107.macro_liquidity_monitor (Plan 3), vm107.macro_review_agent (Plan 6)
      - 1 notification_channel: agent_webhook (Plan 6)
    """
    contracts = list((REGISTRY_ROOT / "contract").glob("universal_alert_engine.yaml"))
    notification_channels = list(
        (REGISTRY_ROOT / "notification_channel").glob("agent_webhook.yaml")
    )
    # Event types: all alert-related events from Phase 91
    event_types = [
        REGISTRY_ROOT / "event_type" / name for name in (
            "regime_change_alert.yaml",
            "correlation_break_alert.yaml",
            "liquidity_stress_alert.yaml",
            "discovery_alert.yaml",
            "release_alert.yaml",
            "macro_indicator_threshold_alert.yaml",
        )
    ]
    # Agent profiles for Phase 91
    agent_profiles = [
        REGISTRY_ROOT / "agent_profile" / "vm107.macro_indicator_alert_emitter.yaml",
        REGISTRY_ROOT / "agent_profile" / "vm107.macro_liquidity_monitor.yaml",
        REGISTRY_ROOT / "agent_profile" / "vm107.macro_review_agent.yaml",
    ]

    existing_contracts = [p for p in contracts if p.exists()]
    existing_channels = [p for p in notification_channels if p.exists()]
    existing_events = [p for p in event_types if p.exists()]
    existing_profiles = [p for p in agent_profiles if p.exists()]

    total = (
        len(existing_contracts)
        + len(existing_channels)
        + len(existing_events)
        + len(existing_profiles)
    )

    assert total >= 11, (
        f"Phase 91 final registry tally must be ≥ 11 entries (REQ-91-10); "
        f"got {total}: contracts={len(existing_contracts)}, "
        f"notification_channels={len(existing_channels)}, "
        f"event_types={len(existing_events)}, agent_profiles={len(existing_profiles)}"
    )
