"""Tests for VM107 replay template YAML registry entries — CONTEXT §6, §20.

Each event type must have at least one template YAML in:
VM107/registry/replay_template/<event_type>/<template_id>.yaml

Graduates in 59-03 when YAMLs are created.
"""
import pytest
from pathlib import Path


TEMPLATE_DIR = Path("/Volumes/ HardDrive/FinGPT/VM107/registry/replay_template")


@pytest.mark.xfail(strict=True, reason="Phase 59 — template YAMLs land in 59-03")
def test_template_dir_exists():
    """registry/replay_template/ directory must exist."""
    assert TEMPLATE_DIR.exists(), f"Template directory missing: {TEMPLATE_DIR}"


@pytest.mark.xfail(strict=True, reason="Phase 59 — template YAMLs land in 59-03")
def test_at_least_one_template_yaml():
    """registry/replay_template/ must contain at least one YAML file."""
    yamls = list(TEMPLATE_DIR.rglob("*.yaml"))
    assert len(yamls) > 0, "No template YAMLs found in registry/replay_template/"


@pytest.mark.xfail(strict=True, reason="Phase 59 — template YAMLs land in 59-03")
def test_template_yaml_has_required_keys():
    """Each template YAML must have: id, event_type, version, template fields."""
    import yaml
    yamls = list(TEMPLATE_DIR.rglob("*.yaml"))
    if not yamls:
        pytest.skip("No YAMLs to validate")
    for yaml_path in yamls:
        data = yaml.safe_load(yaml_path.read_text())
        assert "id" in data, f"{yaml_path}: missing 'id'"
        assert "event_type" in data, f"{yaml_path}: missing 'event_type'"
        assert "version" in data, f"{yaml_path}: missing 'version'"
        assert "template" in data, f"{yaml_path}: missing 'template'"


@pytest.mark.xfail(strict=True, reason="Phase 59 — template YAMLs land in 59-03")
def test_core_event_types_have_templates():
    """Core event types must have templates per CONTEXT §2."""
    import yaml
    yamls = list(TEMPLATE_DIR.rglob("*.yaml"))
    if not yamls:
        pytest.skip("No YAMLs to validate")
    event_types_found = set()
    for yaml_path in yamls:
        data = yaml.safe_load(yaml_path.read_text())
        event_types_found.add(data.get("event_type"))
    required = {"checklist_completed", "order_submitted", "position_closed"}
    missing = required - event_types_found
    assert not missing, f"Missing templates for core event types: {missing}"
