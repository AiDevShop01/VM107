"""Per-entry registry validation for get_primitives (HOW-TO-ADD-TOOLS.md §0 line 319).

Asserts:
  - YAML well-formed
  - Required fields present (id, type, status, location.source, location.contracts.{request,response})
  - location.source path actually exists on disk
  - Contract dotted-paths resolve via importlib (no typos in module/class names)
"""
import importlib
import pathlib

import pytest
import yaml


REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "registry"
    / "tool"
    / "get_primitives.yaml"
)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]  # parent of VM107


@pytest.fixture(scope="module")
def entry() -> dict:
    assert REGISTRY_PATH.exists(), f"Registry YAML not found: {REGISTRY_PATH}"
    return yaml.safe_load(REGISTRY_PATH.read_text())


def test_yaml_well_formed(entry):
    assert isinstance(entry, dict)
    assert entry["id"] == "get_primitives"
    assert entry["type"] == "tool"
    assert entry["status"] in {"real", "stub", "planned"}


def test_required_fields_present(entry):
    for field in ("id", "type", "status", "location", "api_structure", "impact_on_decision"):
        assert field in entry, f"Missing required field: {field}"
    loc = entry["location"]
    for field in ("source", "contracts"):
        assert field in loc, f"Missing location.{field}"
    for field in ("request", "response"):
        assert field in loc["contracts"], f"Missing location.contracts.{field}"


def test_source_path_exists(entry):
    """location.source MUST exist on disk — catches typos and stale entries."""
    source_rel = entry["location"]["source"]
    source_abs = REPO_ROOT / source_rel
    assert source_abs.exists(), (
        f"location.source does not exist: {source_abs}. "
        f"Either fix the YAML or ship the source file."
    )


def test_contracts_importable(entry):
    """Contract dotted paths MUST resolve — catches typos in module/class names."""
    for kind in ("request", "response"):
        dotted = entry["location"]["contracts"][kind]
        module_path, _, class_name = dotted.rpartition(".")
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            pytest.fail(f"Cannot import {module_path} for {kind}: {e}")
        assert hasattr(module, class_name), (
            f"{module_path} has no attribute {class_name} (declared in registry as "
            f"{kind} contract for get_primitives)"
        )
