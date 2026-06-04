"""REQ-83-6 — Three new Phase 83 capability YAML files must exist and be schema-valid.

Wave 6 Plan 12 will GREEN these tests by shipping:
  VM107/registry/tool/vm101.fred_calendar.yaml (NEW — Phase 83 Wave 1)
  VM107/registry/tool/vm107.intelligence_feed.macro.yaml (EXISTS — verify Phase 83 updates)
  VM107/registry/tool/vm107.novelty_engine.yaml (NEW — Phase 83 Wave 4)

Each YAML must conform to the Phase 47.6 capability schema (all required fields present).
The existing test_all_tool_yamls_have_envelope_fields.py validates format; these tests
validate the Phase 83-specific content (capability_type, vm, endpoint path, etc.).
"""
import pytest
from pathlib import Path

VM107_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_TOOL_DIR = VM107_ROOT / "registry" / "tool"


@pytest.mark.phase83
def test_vm101_fred_calendar_yaml_exists():
    """VM107/registry/tool/vm101.fred_calendar.yaml exists after Wave 6 deployment.

    REQ-83-6: The VM101 FRED calendar service must have a capability YAML so VM107
    agents can discover it via the Phase 47.6 registry loader.
    """
    yaml_file = REGISTRY_TOOL_DIR / "vm101.fred_calendar.yaml"
    assert yaml_file.exists(), (
        f"REQ-83-6 FAIL: {yaml_file} does not exist. "
        "Wave 6 Plan 12 must create this capability YAML."
    )


@pytest.mark.phase83
def test_vm101_fred_calendar_yaml_has_required_fields():
    """vm101.fred_calendar.yaml has all Phase 47.6 required fields.

    REQ-83-6: Required fields per Phase 47.6 schema: id, type, status, shipped,
    last_changed, name, description, capability_type, vm, vm107_endpoint_path,
    typical_confidence, expected_freshness_seconds, is_deterministic, version.
    """
    import yaml

    yaml_file = REGISTRY_TOOL_DIR / "vm101.fred_calendar.yaml"
    if not yaml_file.exists():
        pytest.fail("RED skeleton — Wave 6 Plan 12 will GREEN this (file doesn't exist yet)")

    data = yaml.safe_load(yaml_file.read_text())
    required = ["id", "type", "status", "vm", "capability_type", "version",
                "typical_confidence", "expected_freshness_seconds", "is_deterministic"]
    missing = [k for k in required if k not in data]
    assert not missing, f"vm101.fred_calendar.yaml missing required fields: {missing}"


@pytest.mark.phase83
def test_vm107_novelty_engine_yaml_exists():
    """VM107/registry/tool/vm107.novelty_engine.yaml exists after Wave 4 deployment.

    REQ-83-6: The NoveltyEngine V1 must have a capability YAML so agents can
    discover and use it via the Phase 47.6 registry.
    """
    yaml_file = REGISTRY_TOOL_DIR / "vm107.novelty_engine.yaml"
    assert yaml_file.exists(), (
        f"REQ-83-6 FAIL: {yaml_file} does not exist. "
        "Wave 4 Plan 09 must create this capability YAML."
    )


@pytest.mark.phase83
def test_vm107_intelligence_feed_macro_yaml_updated_for_phase83():
    """vm107.intelligence_feed.macro.yaml has Phase 83 updates (shipped field >= 83).

    REQ-83-6: The existing MACRO intelligence feed YAML was shipped in Phase 65/66.
    Phase 83 updates the endpoint path, capability_type, and shipped field to
    reflect the LLM-router refactor and NoveltyEngine addition.
    """
    import yaml

    yaml_file = REGISTRY_TOOL_DIR / "vm107.intelligence_feed.macro.yaml"
    assert yaml_file.exists(), f"vm107.intelligence_feed.macro.yaml not found at {yaml_file}"

    data = yaml.safe_load(yaml_file.read_text())
    shipped = data.get("shipped", 0)
    assert int(str(shipped)) >= 83, (
        f"vm107.intelligence_feed.macro.yaml has shipped={shipped!r}, expected >= 83. "
        "Wave 6 Plan 12 must update the shipped field to reflect Phase 83 changes."
    )
    pytest.fail("RED skeleton — Wave 6 Plan 12 will GREEN this")
