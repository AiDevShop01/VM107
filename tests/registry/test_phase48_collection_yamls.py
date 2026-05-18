"""Phase 48 Plan 48-02 Task 2.3 — REQ-48-REG.

Validates the 4 new collection-registry YAML entries shipped by Plan 48-02:

  - VM107/registry/collection/refinement_loops.yaml
  - VM107/registry/collection/accepted_strategies.yaml
  - VM107/registry/collection/rejected_strategies.yaml
  - VM107/registry/collection/critic_verdicts.yaml

For each YAML this test asserts:
  1. File exists at the expected path.
  2. YAML parses.
  3. Required fields are present and match Phase 47.6 + Phase 48 contract:
     id, type=collection, status (real|experimental|stub|deprecated),
     impact_on_decision (HIGH|MEDIUM|LOW), worm=true, producer=VM107,
     storage=mongodb, phase=48.
  4. `schema:` points at a real Pydantic class importable from
     core.contracts.schemas (where Plan 48-01 just landed the contracts).
     critic_verdicts.yaml -> CriticVerdict
     refinement_loops.yaml -> RefinementLoopState
     accepted_strategies.yaml and rejected_strategies.yaml: schema field
     OPTIONAL (Pydantic contracts for these collections land in Plan 08a's
     acceptance/rejection emitter — Plan 02 only ships the storage substrate).
  5. Tag list contains "phase-48".
  6. YAML id matches the COLLECTION constant in the corresponding migration script.
  7. Each YAML carries the REGISTER_CAPABILITY header comment per
     Phase 47.6 plan-checker discipline.
  8. The full registry passes the 7-stage validator (no regressions).

Fail-fast: each YAML is its own subtest; first failure short-circuits via -x.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = REPO_ROOT / "registry" / "collection"
MIGRATIONS_DIR = REPO_ROOT / "core" / "migrations" / "scripts"


# Mapping: yaml file -> {migration_file, expected_schema_or_None}
COLLECTIONS_UNDER_TEST = {
    "refinement_loops.yaml": {
        "migration": "014_refinement_loops.py",
        "expected_schema": "core.contracts.schemas.RefinementLoopState",
    },
    "accepted_strategies.yaml": {
        "migration": "015_accepted_strategies.py",
        "expected_schema": None,  # Pydantic contract lands in Plan 08a
    },
    "rejected_strategies.yaml": {
        "migration": "016_rejected_strategies.py",
        "expected_schema": None,  # Pydantic contract lands in Plan 08a
    },
    "critic_verdicts.yaml": {
        "migration": "018_critic_verdicts.py",
        "expected_schema": "core.contracts.schemas.CriticVerdict",
    },
}


def _load_yaml(name: str) -> dict:
    path = REGISTRY_DIR / name
    assert path.exists(), f"YAML missing: {path}"
    with path.open() as f:
        return yaml.safe_load(f)


def _read_yaml_raw(name: str) -> str:
    return (REGISTRY_DIR / name).read_text()


def _migration_collection_constant(migration_file: str) -> str:
    """Load the migration module and return its COLLECTION constant."""
    path = MIGRATIONS_DIR / migration_file
    spec = importlib.util.spec_from_file_location(migration_file, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.COLLECTION


@pytest.mark.parametrize("yaml_name", list(COLLECTIONS_UNDER_TEST))
def test_yaml_exists_and_parses(yaml_name):
    data = _load_yaml(yaml_name)
    assert isinstance(data, dict)


@pytest.mark.parametrize("yaml_name", list(COLLECTIONS_UNDER_TEST))
def test_required_fields(yaml_name):
    data = _load_yaml(yaml_name)
    assert data.get("type") == "collection"
    assert data.get("status") in {"real", "experimental", "stub", "deprecated"}
    assert data.get("impact_on_decision") in {"HIGH", "MEDIUM", "LOW"}
    assert data.get("worm") is True, "Phase 48 collections require worm=true"
    assert data.get("producer") == "VM107"
    assert data.get("storage") == "mongodb"
    assert data.get("phase") == 48


@pytest.mark.parametrize("yaml_name", list(COLLECTIONS_UNDER_TEST))
def test_schema_field_points_at_real_pydantic_class(yaml_name):
    data = _load_yaml(yaml_name)
    expected = COLLECTIONS_UNDER_TEST[yaml_name]["expected_schema"]
    schema_value = data.get("schema")
    if expected is None:
        # accepted_strategies / rejected_strategies — schema field allowed to
        # be missing OR present-but-pointing-at-a-placeholder dotted path.
        # If present, it must at least be a string.
        if schema_value is not None:
            assert isinstance(schema_value, str)
        return
    assert schema_value == expected, (
        f"{yaml_name} schema={schema_value!r}, expected {expected!r}"
    )
    # And the class must actually be importable.
    module_path, class_name = expected.rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    assert hasattr(module, class_name), (
        f"{expected} does not exist after Plan 48-01"
    )


@pytest.mark.parametrize("yaml_name", list(COLLECTIONS_UNDER_TEST))
def test_phase_48_tag_present(yaml_name):
    data = _load_yaml(yaml_name)
    tags = data.get("tags", [])
    assert "phase-48" in tags, f"{yaml_name} missing phase-48 tag (got {tags})"


@pytest.mark.parametrize("yaml_name", list(COLLECTIONS_UNDER_TEST))
def test_id_matches_migration_collection(yaml_name):
    data = _load_yaml(yaml_name)
    migration_file = COLLECTIONS_UNDER_TEST[yaml_name]["migration"]
    expected_id = _migration_collection_constant(migration_file)
    assert data["id"] == expected_id, (
        f"{yaml_name} id={data['id']!r}, but migration {migration_file} "
        f"defines COLLECTION={expected_id!r}"
    )


@pytest.mark.parametrize("yaml_name", list(COLLECTIONS_UNDER_TEST))
def test_register_capability_directive_present(yaml_name):
    """Phase 47.6 plan-checker discipline: each YAML carries a
    REGISTER_CAPABILITY header comment naming type, id, and path."""
    raw = _read_yaml_raw(yaml_name)
    pattern = re.compile(
        r"#\s*REGISTER_CAPABILITY:.*type=collection.*id=\S+.*path=\S+",
        re.IGNORECASE,
    )
    assert pattern.search(raw), (
        f"{yaml_name} missing # REGISTER_CAPABILITY header comment "
        f"(must include type=collection, id=<name>, path=<relative path>)"
    )


def test_full_registry_validator_still_passes():
    """The 7-stage validator must not regress on the new YAMLs.

    Imports run_full_pipeline lazily so collection of this test doesn't fail
    when the validator module isn't on sys.path during pytest collection.
    """
    from core.registry.validation import run_full_pipeline

    registry_root = REPO_ROOT / "registry"
    # If this raises RegistryValidationError, the new YAMLs broke something.
    entries = run_full_pipeline(registry_root)

    # Sanity: the 4 new ids appear in the validated set.
    ids = {e.id for e in entries}
    assert {"refinement_loops", "accepted_strategies", "rejected_strategies", "critic_verdicts"}.issubset(ids), (
        f"Phase 48 collection entries missing from validated registry. Got: "
        f"{sorted(i for i in ids if 'refinement' in i or 'strateg' in i or 'critic' in i)}"
    )
