"""Per-entry registry validation for get_liquidity_context (HOW-TO-ADD-TOOLS.md §0 line 319)."""
import importlib
import pathlib

import pytest
import yaml


REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "registry"
    / "tool"
    / "get_liquidity_context.yaml"
)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def entry() -> dict:
    assert REGISTRY_PATH.exists(), f"Registry YAML not found: {REGISTRY_PATH}"
    return yaml.safe_load(REGISTRY_PATH.read_text())


def test_yaml_well_formed(entry):
    assert isinstance(entry, dict)
    assert entry["id"] == "get_liquidity_context"
    assert entry["type"] == "tool"
    assert entry["status"] in {"real", "stub", "planned"}


def test_required_fields_present(entry):
    for field in ("id", "type", "status", "location", "api_structure", "impact_on_decision"):
        assert field in entry
    loc = entry["location"]
    for field in ("source", "contracts"):
        assert field in loc
    for field in ("request", "response"):
        assert field in loc["contracts"]


def test_source_path_exists(entry):
    source_rel = entry["location"]["source"]
    source_abs = REPO_ROOT / source_rel
    assert source_abs.exists(), f"location.source does not exist: {source_abs}"


def test_contracts_importable(entry):
    for kind in ("request", "response"):
        dotted = entry["location"]["contracts"][kind]
        module_path, _, class_name = dotted.rpartition(".")
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            pytest.fail(f"Cannot import {module_path} for {kind}: {e}")
        assert hasattr(module, class_name), (
            f"{module_path} has no attribute {class_name}"
        )
