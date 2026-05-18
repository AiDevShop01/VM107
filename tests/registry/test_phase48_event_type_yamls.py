"""Phase 48 Plan 07 — 10 Phase 56 event_type registry YAMLs.

Each YAML at VM107/registry/event_type/<event_name>.yaml carries the
Phase 47.6 required shape PLUS the planner-V1 locked
``causality_scope_default: IDEA`` field (CONTEXT § Decision 18).

REQ-48-D18 (Phase 56 single temporal truth substrate).
REQ-48-REG (Phase 47.6 capability registry mandate).
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
import yaml

# Locked: 10 Phase 48 lifecycle event types. CONTEXT § Decision 18.
PHASE48_EVENT_TYPE_IDS = (
    "refinement_loop_started",
    "iteration_started",
    "critic_verdict_received",
    "hard_veto_triggered",
    "identity_drift_detected",
    "convergence_stall_detected",
    "budget_exceeded",
    "strategy_accepted",
    "strategy_rejected",
    "loop_terminated",
)

# Per-event payload field expectations (planner-locked; see Plan 07 <action>).
PHASE48_EVENT_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "refinement_loop_started": frozenset(
        {"loop_id", "task_id", "root_hypothesis_id", "strategy_family", "registry_snapshot_hash"}
    ),
    "iteration_started": frozenset(
        {"loop_id", "iteration_number", "root_hypothesis_id", "registry_snapshot_hash"}
    ),
    "critic_verdict_received": frozenset(
        {"loop_id", "iteration_number", "critic_verdict_id", "verdict", "confidence", "refinement_targets_count"}
    ),
    "hard_veto_triggered": frozenset(
        {"loop_id", "iteration_number", "vetoes_triggered"}
    ),
    "identity_drift_detected": frozenset(
        {"loop_id", "iteration_number", "identity_score", "threshold", "identity_diff_breakdown"}
    ),
    "convergence_stall_detected": frozenset(
        {"loop_id", "iteration_number", "repeated_targets"}
    ),
    "budget_exceeded": frozenset(
        {"loop_id", "iteration_number", "scope", "consumed_usd", "cap_usd"}
    ),
    "strategy_accepted": frozenset(
        {"loop_id", "accepted_strategy_id", "root_hypothesis_id", "final_iteration", "registry_yaml_path"}
    ),
    "strategy_rejected": frozenset(
        {"loop_id", "rejected_strategy_id", "root_hypothesis_id", "termination_reason", "final_iteration"}
    ),
    "loop_terminated": frozenset(
        {"loop_id", "termination_reason", "final_iteration", "total_cost_usd"}
    ),
}

# Terminal-decision events are HIGH impact; others MEDIUM.
PHASE48_HIGH_IMPACT_IDS = frozenset(
    {"strategy_accepted", "strategy_rejected", "loop_terminated"}
)

# Lifecycle category for terminal events (3); cognition for the others (7).
PHASE48_LIFECYCLE_CATEGORY_IDS = frozenset(
    {"strategy_accepted", "strategy_rejected", "loop_terminated"}
)


def _yaml_path(event_id: str) -> Path:
    return _VM107_ROOT / "registry" / "event_type" / f"{event_id}.yaml"


def _load_yaml(event_id: str) -> dict:
    p = _yaml_path(event_id)
    return yaml.safe_load(p.read_text())


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_exists(event_id):
    """Each Phase 48 event_type YAML exists on disk."""
    p = _yaml_path(event_id)
    assert p.exists(), f"Missing registry YAML at {p}"


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_required_fields(event_id):
    """YAML carries the Phase 47.6 required shape."""
    data = _load_yaml(event_id)
    assert data["id"] == event_id
    assert data["type"] == "event_type"
    assert data["status"] == "real"
    assert data["shipped"] == 48
    assert data["phase"] == 48
    assert data["producer"] == "VM107"
    assert isinstance(data.get("description"), str) and len(data["description"]) > 0
    assert data["version"] == "1.0.0"
    assert data["deprecated"] is False
    # Events are observable across consumers — never hard-scoped.
    assert data["hard_scoped"] is False


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_causality_scope_locked_to_idea(event_id):
    """Planner-V1 lock: causality_scope_default == 'IDEA' across all 10 events.

    Avoids Phase 56 schema migration. CONTEXT § Decision 18.
    """
    data = _load_yaml(event_id)
    assert data["causality_scope_default"] == "IDEA", (
        f"{event_id}: causality_scope_default must equal 'IDEA' "
        f"(planner V1 lock — see CONTEXT § Decision 18)."
    )


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_payload_fields_match_plan(event_id):
    """YAML payload_fields dict matches the planner-locked schema for this event."""
    data = _load_yaml(event_id)
    payload = data.get("payload_fields")
    assert isinstance(payload, dict) and len(payload) > 0, (
        f"{event_id}: payload_fields must be a non-empty mapping"
    )
    expected = PHASE48_EVENT_PAYLOAD_FIELDS[event_id]
    actual = frozenset(payload.keys())
    assert actual == expected, (
        f"{event_id}: payload_fields keys {sorted(actual)} != expected {sorted(expected)}"
    )


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_impact_on_decision(event_id):
    """Terminal events HIGH impact; lifecycle events MEDIUM impact."""
    data = _load_yaml(event_id)
    expected = "HIGH" if event_id in PHASE48_HIGH_IMPACT_IDS else "MEDIUM"
    assert data["impact_on_decision"] == expected, (
        f"{event_id}: impact_on_decision == {data['impact_on_decision']} "
        f"but expected {expected}"
    )


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_category(event_id):
    """Terminal events use 'lifecycle' category; others use 'cognition'."""
    data = _load_yaml(event_id)
    expected = "lifecycle" if event_id in PHASE48_LIFECYCLE_CATEGORY_IDS else "cognition"
    assert data["category"] == expected, (
        f"{event_id}: category == {data['category']} but expected {expected}"
    )


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_consumers_includes_phase56(event_id):
    """All Phase 48 events flow into the Phase 56 canonical store."""
    data = _load_yaml(event_id)
    assert "phase_56_event_store" in data.get("consumers", []), (
        f"{event_id}: consumers must include 'phase_56_event_store'"
    )


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_related_capabilities_includes_orchestrator(event_id):
    """Sole emitter authority: orchestrator listed as related capability."""
    data = _load_yaml(event_id)
    assert "refinement_orchestrator" in data.get("related_capabilities", []), (
        f"{event_id}: related_capabilities must include 'refinement_orchestrator'"
    )


@pytest.mark.parametrize("event_id", PHASE48_EVENT_TYPE_IDS)
def test_event_type_yaml_tags(event_id):
    """Tags include phase-48, category tag, and refinement_loop label."""
    data = _load_yaml(event_id)
    tags = data.get("tags", [])
    assert "phase-48" in tags, f"{event_id}: tags missing 'phase-48'"
    assert "refinement_loop" in tags, f"{event_id}: tags missing 'refinement_loop'"
    expected_cat = (
        "lifecycle" if event_id in PHASE48_LIFECYCLE_CATEGORY_IDS else "cognition"
    )
    assert expected_cat in tags, f"{event_id}: tags missing '{expected_cat}'"


def test_event_type_yamls_cross_link_via_related_events():
    """The 10 events form an interconnected lifecycle graph.

    Each YAML's ``related_events`` list points at AT LEAST one other Phase 48
    event id, so consumers can navigate the lifecycle without a separate
    topology index.
    """
    all_ids = set(PHASE48_EVENT_TYPE_IDS)
    cross_link_failures: list[str] = []
    for event_id in PHASE48_EVENT_TYPE_IDS:
        data = _load_yaml(event_id)
        related = set(data.get("related_events", []))
        overlap = related & all_ids
        if not overlap:
            cross_link_failures.append(event_id)
    assert not cross_link_failures, (
        "Each Phase 48 event_type YAML must link to ≥1 other Phase 48 event "
        f"via related_events; offenders: {cross_link_failures}"
    )


def test_event_type_yamls_pass_registry_validation():
    """All 10 event_type YAMLs pass core/registry/validation.py stages 1-2.

    Stage 1 = YAML syntax (loader.py raises on parse fail).
    Stage 2 = Pydantic schema validation (id/type/status/impact_on_decision).
    """
    from core.registry.loader import load_all_yamls
    from core.registry.validation import validate_schemas

    event_type_dir = _VM107_ROOT / "registry" / "event_type"
    raw = load_all_yamls(event_type_dir)
    # Filter to Phase 48 ones for focused validation.
    phase48_raw = [(p, d) for (p, d) in raw if d.get("id") in PHASE48_EVENT_TYPE_IDS]
    assert len(phase48_raw) == 10, (
        f"Expected 10 Phase 48 event_type YAMLs, found {len(phase48_raw)}"
    )
    # Validate stage 2 — raises RegistryValidationError on any failure.
    validate_schemas(phase48_raw)


def test_register_capability_header_comment_present():
    """Each event_type YAML carries the REGISTER_CAPABILITY header comment.

    Documents the capability registry mandate (Phase 47.6) so the YAML's
    intent is obvious without cross-referencing the registry tooling.
    """
    missing: list[str] = []
    for event_id in PHASE48_EVENT_TYPE_IDS:
        p = _yaml_path(event_id)
        first_line = p.read_text().splitlines()[0]
        if "REGISTER_CAPABILITY" not in first_line or event_id not in first_line:
            missing.append(event_id)
    assert not missing, (
        f"Event_type YAMLs missing REGISTER_CAPABILITY header: {missing}"
    )
