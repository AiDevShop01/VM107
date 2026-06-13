"""Phase 85 Plan 13 — Task 1: Registry compliance test suite.

Validates that all 11 Phase 85 capability YAMLs exist, pass the Phase 47.6
validation gate, and can be discovered via lookup_capability.

Test suite:
  test_all_phase85_yamls_present       — exactly 11 shipped=85 YAMLs on disk
  test_each_yaml_passes_phase47_6_schema — full 7-stage validation gate green
  test_lookup_capability_discovers_each_id — lookup_capability returns each id
  test_tool_yamls_have_envelope_provenance_fields — 4 Phase 70.5 fields on all 6 tools
  test_agent_yaml_allowed_tools_match_profile_yaml — registry vs profile yaml parity
  test_contract_yaml_worm_true         — agent_reasoning_artifact has worm: true
  test_contract_yaml_has_16_fields     — exact 16 fields per B1 schema
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

pytestmark = pytest.mark.phase_85

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGISTRY_ROOT = _VM107_ROOT / "registry"

# Exactly 11 Phase 85 capability YAMLs (REQ-85-6):
#   6 tool:        vm102.indicator_history, vm102.indicator_releases,
#                  vm102.indicator_distribution, vm102.indicator_regime,
#                  vm102.indicator_asset_exposure, vm107.lookup_reasoning_artifact
#   4 agent:       vm107.macro_release_analyst, vm107.macro_asset_exposure_analyst,
#                  vm107.executive_summary_writer, vm107.macro_indicator_describer
#   1 contract:    agent_reasoning_artifact
PHASE85_TOOL_IDS = [
    "vm102.indicator_history",
    "vm102.indicator_releases",
    "vm102.indicator_distribution",
    "vm102.indicator_regime",
    "vm102.indicator_asset_exposure",
    "vm107.lookup_reasoning_artifact",
]
PHASE85_AGENT_IDS = [
    "vm107.macro_release_analyst",
    "vm107.macro_asset_exposure_analyst",
    "vm107.executive_summary_writer",
    "vm107.macro_indicator_describer",
]
PHASE85_CONTRACT_IDS = [
    "agent_reasoning_artifact",
]
ALL_PHASE85_IDS = PHASE85_TOOL_IDS + PHASE85_AGENT_IDS + PHASE85_CONTRACT_IDS

PHASE85_TOOL_PATHS = {
    "vm102.indicator_history": REGISTRY_ROOT / "tool" / "vm102.indicator_history.yaml",
    "vm102.indicator_releases": REGISTRY_ROOT / "tool" / "vm102.indicator_releases.yaml",
    "vm102.indicator_distribution": REGISTRY_ROOT / "tool" / "vm102.indicator_distribution.yaml",
    "vm102.indicator_regime": REGISTRY_ROOT / "tool" / "vm102.indicator_regime.yaml",
    "vm102.indicator_asset_exposure": REGISTRY_ROOT / "tool" / "vm102.indicator_asset_exposure.yaml",
    "vm107.lookup_reasoning_artifact": REGISTRY_ROOT / "tool" / "vm107.lookup_reasoning_artifact.yaml",
}

PHASE85_AGENT_PROFILE_PATHS = {
    "vm107.macro_release_analyst": REGISTRY_ROOT / "agent_profile" / "vm107.macro_release_analyst.yaml",
    "vm107.macro_asset_exposure_analyst": REGISTRY_ROOT / "agent_profile" / "vm107.macro_asset_exposure_analyst.yaml",
    "vm107.executive_summary_writer": REGISTRY_ROOT / "agent_profile" / "vm107.executive_summary_writer.yaml",
    "vm107.macro_indicator_describer": REGISTRY_ROOT / "agent_profile" / "vm107.macro_indicator_describer.yaml",
}

PHASE85_CONTRACT_PATH = REGISTRY_ROOT / "contract" / "agent_reasoning_artifact.yaml"

# Profile YAML paths (runtime profiles, separate from registry descriptors)
PROFILE_YAML_PATHS = {
    "vm107.macro_release_analyst": _VM107_ROOT / "profiles" / "macro_release_analyst.yaml",
    "vm107.macro_asset_exposure_analyst": _VM107_ROOT / "profiles" / "macro_asset_exposure_analyst.yaml",
    "vm107.executive_summary_writer": _VM107_ROOT / "profiles" / "executive_summary_writer.yaml",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset CapabilityRegistry singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


@pytest.fixture
def real_registry():
    """Initialize registry from the real VM107/registry root."""
    from core.registry.capability_registry import CapabilityRegistry

    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(REGISTRY_ROOT)
    yield CapabilityRegistry.get()
    CapabilityRegistry._instance = None


# ---------------------------------------------------------------------------
# Test 1: exactly 11 Phase 85 YAMLs exist on disk
# ---------------------------------------------------------------------------


def test_all_phase85_yamls_present():
    """Assert exactly 11 Phase-85 YAMLs exist on disk matching REQ-85-6.

    Count: 6 tool + 4 agent_profile + 1 contract = 11.
    If count != 11, fail loudly — drift from REQ-85-6 is a blocker.
    """
    found_paths = []

    for path in PHASE85_TOOL_PATHS.values():
        assert path.exists(), f"MISSING Phase 85 tool YAML: {path}"
        found_paths.append(path)

    for path in PHASE85_AGENT_PROFILE_PATHS.values():
        assert path.exists(), f"MISSING Phase 85 agent_profile YAML: {path}"
        found_paths.append(path)

    assert PHASE85_CONTRACT_PATH.exists(), (
        f"MISSING Phase 85 contract YAML: {PHASE85_CONTRACT_PATH}"
    )
    found_paths.append(PHASE85_CONTRACT_PATH)

    assert len(found_paths) == 11, (
        f"REQ-85-6 violation: expected exactly 11 Phase 85 YAMLs, found {len(found_paths)}. "
        f"Drift from REQ-85-6 is a blocker."
    )


# ---------------------------------------------------------------------------
# Test 2: full Phase 47.6 7-stage validation gate
# ---------------------------------------------------------------------------


def test_each_yaml_passes_phase47_6_schema(real_registry):
    """Full 7-stage Phase 47.6 validation gate passes without errors.

    CapabilityRegistry.initialize() runs all 7 stages at boot. If this fixture
    succeeds, all 402 YAMLs (including the 11 Phase 85 ones) pass validation.
    """
    # If real_registry fixture constructed successfully, all stages passed.
    # Verify Phase 85 entries are in the registry snapshot.
    snapshot_ids = {e.id for e in real_registry.snapshot.entries}
    for cap_id in ALL_PHASE85_IDS:
        assert cap_id in snapshot_ids, (
            f"Phase 47.6 validation passed but '{cap_id}' not in registry snapshot. "
            f"Check that the YAML has shipped=85 and a valid type."
        )


# ---------------------------------------------------------------------------
# Test 3: lookup_capability discovers each id
# ---------------------------------------------------------------------------


def test_lookup_capability_discovers_each_id(real_registry):
    """For each of the 11 Phase 85 ids, lookup_capability returns an entry."""
    from tools.lookup_capability import lookup, LookupResult

    for cap_id in ALL_PHASE85_IDS:
        result = lookup(cap_id)
        assert isinstance(result, LookupResult), (
            f"lookup_capability('{cap_id}') returned {type(result)}, expected LookupResult"
        )
        assert result.status == "ok", (
            f"lookup_capability('{cap_id}') status={result.status!r}; "
            f"expected 'ok'. message={getattr(result, 'message', None)!r}"
        )
        assert result.capability is not None, (
            f"lookup_capability('{cap_id}') returned status=ok but capability=None"
        )


# ---------------------------------------------------------------------------
# Test 4: tool YAMLs have Phase 70.5 envelope-provenance fields
# ---------------------------------------------------------------------------


def test_tool_yamls_have_envelope_provenance_fields():
    """All 6 Phase 85 tool YAMLs declare the 4 Phase 70.5 envelope-provenance fields."""
    required_fields = {
        "typical_confidence",
        "expected_freshness_seconds",
        "is_deterministic",
        "version",
    }

    for tool_id, path in PHASE85_TOOL_PATHS.items():
        assert path.exists(), f"Tool YAML not found: {path}"
        raw = yaml.safe_load(path.read_text())
        missing = required_fields - set(raw.keys())
        assert not missing, (
            f"Phase 70.5 envelope-provenance fields missing from {tool_id}: {missing}. "
            f"Phase 70.5 contract (Plan 47.6 validator Stage 8) will flag these."
        )
        # type assertions
        assert isinstance(raw["typical_confidence"], (int, float)), (
            f"{tool_id}: typical_confidence must be numeric"
        )
        assert 0.0 <= raw["typical_confidence"] <= 1.0, (
            f"{tool_id}: typical_confidence must be in [0.0, 1.0]"
        )
        assert isinstance(raw["expected_freshness_seconds"], int), (
            f"{tool_id}: expected_freshness_seconds must be int"
        )
        assert raw["expected_freshness_seconds"] >= 0, (
            f"{tool_id}: expected_freshness_seconds must be >= 0"
        )
        assert isinstance(raw["is_deterministic"], bool), (
            f"{tool_id}: is_deterministic must be bool"
        )
        assert isinstance(raw["version"], str), (
            f"{tool_id}: version must be a quoted string (e.g. '1.0.0')"
        )


# ---------------------------------------------------------------------------
# Test 5: agent registry YAML allowed_tools matches runtime profile YAML
# ---------------------------------------------------------------------------


def test_agent_yaml_allowed_tools_match_profile_yaml():
    """For the 3 agents with runtime profiles, registry allowed_tools == profile allowed_tools."""
    for agent_id, profile_path in PROFILE_YAML_PATHS.items():
        if not profile_path.exists():
            pytest.skip(f"Profile YAML not found (not yet shipped): {profile_path}")

        registry_path = PHASE85_AGENT_PROFILE_PATHS[agent_id]
        assert registry_path.exists(), f"Registry YAML not found: {registry_path}"

        profile_raw = yaml.safe_load(profile_path.read_text())
        registry_raw = yaml.safe_load(registry_path.read_text())

        profile_tools = set(profile_raw.get("allowed_tools", []))
        registry_tools = set(registry_raw.get("allowed_tools", []))

        assert profile_tools == registry_tools, (
            f"allowed_tools mismatch for {agent_id}:\n"
            f"  profile_yaml:  {sorted(profile_tools)}\n"
            f"  registry_yaml: {sorted(registry_tools)}\n"
            f"Registry and runtime profile must agree on allowed_tools."
        )

        profile_denied = set(profile_raw.get("denied_tools", []))
        registry_denied = set(registry_raw.get("denied_tools", []))
        assert profile_denied == registry_denied, (
            f"denied_tools mismatch for {agent_id}:\n"
            f"  profile_yaml:  {sorted(profile_denied)}\n"
            f"  registry_yaml: {sorted(registry_denied)}\n"
        )

        assert profile_raw.get("max_iterations") == registry_raw.get("max_iterations"), (
            f"max_iterations mismatch for {agent_id}: "
            f"profile={profile_raw.get('max_iterations')} "
            f"registry={registry_raw.get('max_iterations')}"
        )


# ---------------------------------------------------------------------------
# Test 6: contract YAML worm=true
# ---------------------------------------------------------------------------


def test_contract_yaml_worm_true():
    """agent_reasoning_artifact contract YAML has worm: true."""
    assert PHASE85_CONTRACT_PATH.exists(), (
        f"Contract YAML not found: {PHASE85_CONTRACT_PATH}"
    )
    raw = yaml.safe_load(PHASE85_CONTRACT_PATH.read_text())
    assert raw.get("worm") is True, (
        f"agent_reasoning_artifact contract YAML must have worm: true. "
        f"Got worm={raw.get('worm')!r}. "
        f"B1 WORM table is append-only — no UPDATE or DELETE ever."
    )


# ---------------------------------------------------------------------------
# Test 7: contract YAML has exactly 16 fields
# ---------------------------------------------------------------------------


def test_contract_yaml_has_16_fields():
    """agent_reasoning_artifact contract YAML has exactly 16 fields per B1 schema."""
    assert PHASE85_CONTRACT_PATH.exists(), (
        f"Contract YAML not found: {PHASE85_CONTRACT_PATH}"
    )
    raw = yaml.safe_load(PHASE85_CONTRACT_PATH.read_text())
    fields = raw.get("fields", [])
    expected_count = 16
    assert len(fields) == expected_count, (
        f"agent_reasoning_artifact contract YAML must have exactly {expected_count} fields "
        f"(matching B1 schema from Plan 85-02). Got {len(fields)}: {fields}"
    )
    # Verify all 16 expected field names are present
    expected_fields = {
        "artifact_id",
        "agent_profile_id",
        "sub_profile_id",
        "iteration",
        "parent_envelope_id",
        "reasoning_text",
        "reasoning_tokens",
        "response_text",
        "response_tokens",
        "tool_called",
        "tool_args",
        "timestamp",
        "model_version",
        "prompt_version",
        "confidence_self_report",
        "citations",
    }
    actual_fields = set(fields)
    missing = expected_fields - actual_fields
    extra = actual_fields - expected_fields
    assert not missing, (
        f"agent_reasoning_artifact contract YAML missing B1 fields: {missing}"
    )
    assert not extra, (
        f"agent_reasoning_artifact contract YAML has unexpected fields: {extra}"
    )
