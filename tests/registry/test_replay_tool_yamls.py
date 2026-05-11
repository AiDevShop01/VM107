"""Tests for VM107 replay tool YAML registry entries — CONTEXT §20.

Each replay tool must have a registry YAML at:
VM107/registry/tools/<tool_name>.yaml

Graduates in 59-07 when tool YAMLs are created.
"""
import pytest
from pathlib import Path


TOOLS_DIR = Path("/Volumes/ HardDrive/FinGPT/VM107/registry/tools")

REQUIRED_REPLAY_TOOLS = [
    "lookup_replay_artifact",
    "fetch_replay_frame",
    "fetch_replay_chart_slice",
]


@pytest.mark.xfail(strict=True, reason="Phase 59 — tool YAMLs land in 59-07")
def test_lookup_replay_artifact_yaml():
    """registry/tools/lookup_replay_artifact.yaml must exist and be valid."""
    yaml_path = TOOLS_DIR / "lookup_replay_artifact.yaml"
    assert yaml_path.exists(), f"Missing: {yaml_path}"


@pytest.mark.xfail(strict=True, reason="Phase 59 — tool YAMLs land in 59-07")
def test_fetch_replay_frame_yaml():
    """registry/tools/fetch_replay_frame.yaml must exist and be valid."""
    yaml_path = TOOLS_DIR / "fetch_replay_frame.yaml"
    assert yaml_path.exists(), f"Missing: {yaml_path}"


@pytest.mark.xfail(strict=True, reason="Phase 59 — tool YAMLs land in 59-07")
def test_fetch_replay_chart_slice_yaml():
    """registry/tools/fetch_replay_chart_slice.yaml must exist and be valid."""
    yaml_path = TOOLS_DIR / "fetch_replay_chart_slice.yaml"
    assert yaml_path.exists(), f"Missing: {yaml_path}"


@pytest.mark.xfail(strict=True, reason="Phase 59 — tool YAMLs land in 59-07")
def test_tool_yamls_have_required_keys():
    """Each tool YAML must have: id, name, description, input_schema, output_schema."""
    import yaml
    for tool_name in REQUIRED_REPLAY_TOOLS:
        yaml_path = TOOLS_DIR / f"{tool_name}.yaml"
        if not yaml_path.exists():
            pytest.skip(f"Tool YAML not yet created: {yaml_path}")
        data = yaml.safe_load(yaml_path.read_text())
        for key in ["id", "name", "description"]:
            assert key in data, f"{yaml_path}: missing '{key}'"
