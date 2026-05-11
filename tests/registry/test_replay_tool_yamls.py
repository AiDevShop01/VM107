"""Tests for VM107 replay capability YAML registry entries — CONTEXT §20.

Graduated in 59-07: xfail stubs replaced with full registry-shape tests.

Tests verify:
  - 3 tool YAMLs exist at registry/tool/{name}.yaml
  - 3 service YAMLs exist at registry/service/{name}.yaml
  - All YAMLs parse cleanly with yaml.safe_load
  - Tool YAMLs have Phase 47.6 alias-extended frontmatter (id, type, status,
    shipped, last_changed, name, capability_type, vm100_endpoint_path,
    parameters, return_type, phase, hard_scoped)
  - Service YAMLs have required service-descriptor fields (id, type, status,
    module_path, public_methods, phase)
  - capability_type values are distinct (orthogonal cognition surfaces — §18)
  - All YAMLs declare phase=59 and status='shipped'
"""
import pathlib

import pytest
import yaml

# ---------------------------------------------------------------------------
# Registry root
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "registry"
TOOL_DIR = ROOT / "tool"
SERVICE_DIR = ROOT / "service"

PHASE_59_TOOL_YAML_NAMES = [
    "lookup_replay_artifact.yaml",
    "fetch_replay_frame.yaml",
    "fetch_replay_chart_slice.yaml",
]

PHASE_59_SERVICE_YAML_NAMES = [
    "reconstruction_service.yaml",
    "replay_narrator.yaml",
    "replay_artifact_persister.yaml",
]

EXPECTED_CAPABILITY_TYPES = {"replay_lookup", "replay_frame", "replay_chart"}

# ---------------------------------------------------------------------------
# Tool YAML shape tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PHASE_59_TOOL_YAML_NAMES)
def test_tool_yaml_exists(name: str):
    """Each replay tool YAML must exist at registry/tool/{name}."""
    path = TOOL_DIR / name
    assert path.exists(), f"Missing tool YAML: {path}"


@pytest.mark.parametrize("name", PHASE_59_TOOL_YAML_NAMES)
def test_tool_yaml_parses(name: str):
    """Each replay tool YAML must be valid YAML."""
    path = TOOL_DIR / name
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{name}: expected dict, got {type(data)}"


@pytest.mark.parametrize("name", PHASE_59_TOOL_YAML_NAMES)
def test_tool_yaml_has_required_phase47_6_fields(name: str):
    """Tool YAMLs must have Phase 47.6 alias-extended frontmatter."""
    data = yaml.safe_load((TOOL_DIR / name).read_text())

    # Core identity
    assert "id" in data, f"{name}: missing 'id'"
    assert "type" in data, f"{name}: missing 'type'"
    assert data["type"] == "tool", f"{name}: type must be 'tool'"
    assert "status" in data, f"{name}: missing 'status'"
    assert data["status"] == "shipped", f"{name}: status must be 'shipped'"
    assert "shipped" in data, f"{name}: missing 'shipped'"
    assert data["shipped"] == 59, f"{name}: shipped must be 59"
    assert "last_changed" in data, f"{name}: missing 'last_changed'"
    assert "name" in data, f"{name}: missing 'name'"

    # Capability registry fields
    assert "capability_type" in data, f"{name}: missing 'capability_type'"
    assert data["capability_type"] in EXPECTED_CAPABILITY_TYPES, (
        f"{name}: capability_type '{data['capability_type']}' not in {EXPECTED_CAPABILITY_TYPES}"
    )
    assert "vm100_endpoint_path" in data, f"{name}: missing 'vm100_endpoint_path'"

    # Contract definition
    assert "parameters" in data, f"{name}: missing 'parameters'"
    assert "return_type" in data, f"{name}: missing 'return_type'"

    # Phase and scope
    assert "phase" in data, f"{name}: missing 'phase'"
    assert data["phase"] == 59, f"{name}: phase must be 59"
    assert data.get("hard_scoped") is True, f"{name}: hard_scoped must be true"


@pytest.mark.parametrize("name", PHASE_59_TOOL_YAML_NAMES)
def test_tool_yaml_has_capabilities_list(name: str):
    """Tool YAMLs must have a capabilities list."""
    data = yaml.safe_load((TOOL_DIR / name).read_text())
    assert "capabilities" in data, f"{name}: missing 'capabilities'"
    assert isinstance(data["capabilities"], list), f"{name}: capabilities must be a list"
    assert len(data["capabilities"]) >= 1, f"{name}: capabilities must be non-empty"


def test_capability_type_diversity():
    """Each of the 3 replay tools claims a DIFFERENT capability_type.

    CONTEXT §18 — orthogonal cognition surfaces (lookup, frame, chart).
    """
    types = set()
    for name in PHASE_59_TOOL_YAML_NAMES:
        data = yaml.safe_load((TOOL_DIR / name).read_text())
        types.add(data["capability_type"])
    assert len(types) == 3, (
        f"Tools must have 3 distinct capability_types (got {len(types)}): {types}"
    )
    assert types == EXPECTED_CAPABILITY_TYPES, (
        f"Expected capability types {EXPECTED_CAPABILITY_TYPES}, got {types}"
    )


# ---------------------------------------------------------------------------
# Service YAML shape tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PHASE_59_SERVICE_YAML_NAMES)
def test_service_yaml_exists(name: str):
    """Each replay service YAML must exist at registry/service/{name}."""
    path = SERVICE_DIR / name
    assert path.exists(), f"Missing service YAML: {path}"


@pytest.mark.parametrize("name", PHASE_59_SERVICE_YAML_NAMES)
def test_service_yaml_parses(name: str):
    """Each replay service YAML must be valid YAML."""
    data = yaml.safe_load((SERVICE_DIR / name).read_text())
    assert isinstance(data, dict), f"{name}: expected dict, got {type(data)}"


@pytest.mark.parametrize("name", PHASE_59_SERVICE_YAML_NAMES)
def test_service_yaml_has_required_fields(name: str):
    """Service YAMLs must have Phase 47.6 service-descriptor frontmatter."""
    data = yaml.safe_load((SERVICE_DIR / name).read_text())

    # Core identity
    assert "id" in data, f"{name}: missing 'id'"
    assert "type" in data, f"{name}: missing 'type'"
    assert data["type"] == "service", f"{name}: type must be 'service'"
    assert "status" in data, f"{name}: missing 'status'"
    assert data["status"] == "shipped", f"{name}: status must be 'shipped'"

    # Location
    assert "module_path" in data, f"{name}: missing 'module_path'"
    assert "class_name" in data, f"{name}: missing 'class_name'"

    # API surface
    assert "public_methods" in data, f"{name}: missing 'public_methods'"
    assert isinstance(data["public_methods"], list), (
        f"{name}: public_methods must be a list"
    )

    # Phase
    assert "phase" in data, f"{name}: missing 'phase'"
    assert data["phase"] == 59, f"{name}: phase must be 59"


# ---------------------------------------------------------------------------
# Cross-cutting assertions
# ---------------------------------------------------------------------------


def test_all_yaml_ids_are_unique():
    """All 6 YAML ids must be globally unique within this phase."""
    seen_ids = {}
    for name in PHASE_59_TOOL_YAML_NAMES:
        data = yaml.safe_load((TOOL_DIR / name).read_text())
        yaml_id = data.get("id")
        assert yaml_id not in seen_ids, (
            f"Duplicate id '{yaml_id}' in {name} and {seen_ids[yaml_id]}"
        )
        seen_ids[yaml_id] = name

    for name in PHASE_59_SERVICE_YAML_NAMES:
        data = yaml.safe_load((SERVICE_DIR / name).read_text())
        yaml_id = data.get("id")
        assert yaml_id not in seen_ids, (
            f"Duplicate id '{yaml_id}' in {name} and {seen_ids[yaml_id]}"
        )
        seen_ids[yaml_id] = name
