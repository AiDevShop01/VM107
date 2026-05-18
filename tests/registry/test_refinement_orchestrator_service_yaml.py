"""Phase 48 Plan 48-03 Task 3.3 — refinement_orchestrator service YAML registers.

Implements REQ-48-REG.

Asserts:
- ``registry/service/refinement_orchestrator.yaml`` exists.
- Required fields present per RESEARCH.md § Code Examples lines 710-764:
  id, type=service, status=real, shipped=48, phase=48, producer=VM107,
  hard_scoped=true, deprecated=false, related_capabilities (typed wrappers /
  dependencies), related_events (10 Phase 48 lifecycle events).
- Phase 47.6 full validator pipeline still passes (no regression).
"""
from __future__ import annotations

import pathlib

import pytest
import yaml


_SERVICE_YAML = (
    pathlib.Path(__file__).resolve().parents[2]
    / "registry"
    / "service"
    / "refinement_orchestrator.yaml"
)


@pytest.fixture(scope="module")
def yaml_doc() -> dict:
    assert _SERVICE_YAML.exists(), f"missing: {_SERVICE_YAML}"
    return yaml.safe_load(_SERVICE_YAML.read_text())


# ---------------------------------------------------------------------------
# Shape assertions
# ---------------------------------------------------------------------------


def test_yaml_has_required_top_level_fields(yaml_doc):
    required = {
        "id",
        "type",
        "status",
        "shipped",
        "name",
        "description",
        "version",
        "phase",
        "producer",
        "location",
        "related_capabilities",
        "related_events",
        "tags",
        "hard_scoped",
        "impact_on_decision",
        "allowed_agent_profiles",
        "deprecated",
    }
    missing = required - set(yaml_doc.keys())
    assert not missing, f"YAML missing required keys: {missing}"


def test_yaml_id_and_type_and_status(yaml_doc):
    assert yaml_doc["id"] == "refinement_orchestrator"
    assert yaml_doc["type"] == "service"
    assert yaml_doc["status"] == "real"
    assert yaml_doc["shipped"] == 48
    assert yaml_doc["phase"] == 48
    assert yaml_doc["producer"] == "VM107"
    assert yaml_doc["deprecated"] is False
    assert yaml_doc["hard_scoped"] is True


def test_yaml_location_points_at_pure_python_package(yaml_doc):
    loc = yaml_doc["location"]
    assert isinstance(loc, dict)
    src = loc["source"]
    assert src.startswith("VM107/core/agents/refinement_orchestrator")


def test_yaml_related_capabilities_include_typed_wrappers(yaml_doc):
    related = set(yaml_doc["related_capabilities"])
    expected = {
        "strategy_refinement_critic",
        "lookup_capability",
        "run_idea_agent",
        "run_strategy_agent",
        "run_code_agent",
        "run_build",
        "run_backtest",
        "run_critic",
    }
    missing = expected - related
    assert not missing, f"related_capabilities missing: {missing}"


def test_yaml_related_events_include_all_ten_phase_56_events(yaml_doc):
    related = set(yaml_doc["related_events"])
    expected = {
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
    }
    missing = expected - related
    assert not missing, f"related_events missing: {missing}"


def test_yaml_tags_include_phase_and_orchestration(yaml_doc):
    tags = set(yaml_doc["tags"])
    expected_subset = {"phase-48", "cognition", "orchestration", "deterministic"}
    missing = expected_subset - tags
    assert not missing, f"tags missing: {missing}"


# ---------------------------------------------------------------------------
# Full Phase 47.6 validator pipeline must still pass with this YAML present.
# ---------------------------------------------------------------------------


def test_full_47_6_validator_pipeline_passes_with_orchestrator_yaml():
    from core.registry.validation import run_full_pipeline

    registry_root = _SERVICE_YAML.parents[1]
    entries = run_full_pipeline(registry_root)
    # The new entry must be discovered.
    ids = {e.id for e in entries}
    assert "refinement_orchestrator" in ids
    # Sanity: large registry — no catastrophic regression.
    assert len(entries) >= 100
