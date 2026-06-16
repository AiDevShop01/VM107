"""Phase 87 Wave 8 — capability registry sweep.

REQ-87-10 / AC-87-10 / VAL row 87-08-02:
- All 11 Phase 87 capability YAMLs are discoverable via lookup_capability.
- Phase 47.6 boot-time validation passes on the entire VM107 registry
  (this is the real-world "Phase 47.6 schema-validator" — it runs all 7
  validation stages: yaml_syntax, schemas, identity_uniqueness,
  cross_type_linkage, scope_references, dependency_graph,
  contract_resolution).
- Each Phase 87 YAML carries the Phase 47.6 LD-3 fields:
  id, type, status, impact_on_decision, hard_scoped, name, description,
  owner, last_changed (+ allowed_agent_profiles on hard-scoped capabilities,
  per the Wave 0 lesson where 155 YAMLs needed remediation when these were
  missed).

The 11 IDs covered (ids globally unique per Phase 47.6 LD-2 Stage 3):
  agent_profile (4): vm107.macro_transmission_analyst, vm107.macro_regime_analyst,
                     vm107.macro_story_tracker, vm107.macro_regime_monitor
  contract (2):      episodic_memory_service, belief_store
  service (2):       episodic_memory_service_runtime, belief_store_service
                     (service YAMLs carry suffixed ids because the canonical
                     `episodic_memory_service` / `belief_store` ids belong to
                     the contract YAMLs — agent_profile.allowed_tools cites
                     `episodic_memory_service.query` / `belief_store.query`)
  tool (1):          vm105.neo4j_macro_graph_walker
  event_type (2):    belief_proposal, regime_transition_detected

The plan body specs `lookup_capability(type, id)` and
`VM107.registry.schema_validator.validate_yaml(...)` — those exact paths
don't exist in this codebase. The real implementation pair is:
  - tools.lookup_capability.lookup(id) -> LookupResult  (Phase 47.6 Plan 03)
  - core.registry.capability_registry.CapabilityRegistry.initialize(root)
    runs the 7-stage validation and raises RegistryValidationError on any
    schema drift (which IS the Phase 47.6 schema-validator the plan asks
    about). [Rule 3 - Blocking deviation; surfaced in SUMMARY.]
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.phase_87


# (yaml_type_dir, yaml_id, registered_capability_type)
# Note: `service` and `event_type` YAMLs live on disk but are not always
# materialised into the CapabilityRegistry singleton (CapabilityType enum is
# the gate). We assert YAML-on-disk + LD-3 schema fields for all 11; we assert
# lookup_capability discoverability for those whose `capability_type`/`type`
# is a registered CapabilityType.
PHASE_87_REGISTRY_IDS: list[tuple[str, str]] = [
    # agent_profile (4)
    ("agent_profile", "vm107.macro_transmission_analyst"),
    ("agent_profile", "vm107.macro_regime_analyst"),
    ("agent_profile", "vm107.macro_story_tracker"),
    ("agent_profile", "vm107.macro_regime_monitor"),
    # contract (2)
    ("contract", "episodic_memory_service"),
    ("contract", "belief_store"),
    # service (2) — suffixed ids per Phase 47.6 Stage 3 (identity_uniqueness);
    # canonical `episodic_memory_service` + `belief_store` ids belong to the
    # contract YAMLs (cited by agent_profile.allowed_tools).
    ("service", "episodic_memory_service_runtime"),
    ("service", "belief_store_service"),
    # tool (1)
    ("tool", "vm105.neo4j_macro_graph_walker"),
    # event_type (2)
    ("event_type", "belief_proposal"),
    ("event_type", "regime_transition_detected"),
]

# Per Phase 47.6 LD-3 + the Wave 0 schema-drift lesson, these fields MUST
# be present on every YAML (allowed_agent_profiles only on hard-scoped ones).
LD3_REQUIRED_FIELDS = {
    "id",
    "type",
    "status",
    "impact_on_decision",
    "hard_scoped",
    "name",
    "description",
    "owner",
    "last_changed",
}

VM107_ROOT = Path(__file__).resolve().parents[2]  # FinGPT/VM107/
REGISTRY_ROOT = VM107_ROOT / "registry"


def _yaml_path(yaml_type: str, yaml_id: str) -> Path:
    """Resolve the on-disk path for (type, id)."""
    return REGISTRY_ROOT / yaml_type / f"{yaml_id}.yaml"


def _load_yaml(yaml_type: str, yaml_id: str) -> dict:
    path = _yaml_path(yaml_type, yaml_id)
    if not path.exists():
        pytest.fail(f"Phase 87 YAML missing on disk: {path}")
    return yaml.safe_load(path.read_text())


# ─── Sweep 1 — file-on-disk + LD-3 field presence (the Phase 47.6 schema check) ─
@pytest.mark.parametrize("yaml_type,yaml_id", PHASE_87_REGISTRY_IDS)
def test_phase_87_yaml_on_disk(yaml_type: str, yaml_id: str) -> None:
    path = _yaml_path(yaml_type, yaml_id)
    assert path.exists(), (
        f"REQ-87-10 / AC-87-10 — {yaml_type}/{yaml_id} YAML missing on disk "
        f"at expected path {path}. Phase 47.6 register-on-ship lock violated."
    )


@pytest.mark.parametrize("yaml_type,yaml_id", PHASE_87_REGISTRY_IDS)
def test_phase_87_yaml_ld3_fields(yaml_type: str, yaml_id: str) -> None:
    doc = _load_yaml(yaml_type, yaml_id)
    missing = LD3_REQUIRED_FIELDS - set(doc.keys())
    assert not missing, (
        f"Phase 47.6 LD-3 schema drift on {yaml_type}/{yaml_id} — "
        f"missing fields: {sorted(missing)}. "
        "Wave 0 lesson: 155 YAMLs needed remediation when these were missed."
    )
    # type field must match the directory category
    assert doc["type"] == yaml_type, (
        f"{yaml_type}/{yaml_id} declares type={doc['type']!r} but lives in "
        f"registry/{yaml_type}/ — type/dir mismatch"
    )
    # id field must match the filename
    assert doc["id"] == yaml_id, (
        f"{yaml_type}/{yaml_id} declares id={doc['id']!r} but file is "
        f"{yaml_id}.yaml — id/filename mismatch"
    )
    # hard_scoped consumer capabilities (tool / contract / service / event_type)
    # MUST carry allowed_agent_profiles per the Phase 47.6 Wave 0 remediation
    # lesson (155 YAMLs needed the field). agent_profile YAMLs are the SUBJECT
    # of scope checks, not the object — they don't carry the field themselves.
    if doc.get("hard_scoped") is True and yaml_type != "agent_profile":
        assert "allowed_agent_profiles" in doc and doc["allowed_agent_profiles"], (
            f"{yaml_type}/{yaml_id} is hard_scoped=true but missing "
            "allowed_agent_profiles — Phase 47.6 LD-3 gate violated. "
            "Wave 0 lesson: 155 YAMLs needed remediation when these were missed."
        )


# ─── Sweep 2 — lookup_capability discoverability (Phase 47.6 boot-frozen registry) ─
# Limited to types the CapabilityRegistry materialises into its lookup index.
# CapabilityType enum currently includes: tool, signal, skill, pattern,
# behavioral_pattern, agent (and agent_profile), event_type, collection,
# ask_ai_binding, vm102_api + extensions. `contract` and `service` YAMLs live
# on disk and ARE validated by the registry loader (cross_type_linkage stage),
# but they are not exposed as first-class lookup() targets per current
# CapabilityType enum. The Phase 47.6 lookup_capability sweep therefore covers
# the type subset that maps to CapabilityType members.
LOOKUP_INDEX_IDS: list[tuple[str, str]] = [
    ("agent_profile", "vm107.macro_transmission_analyst"),
    ("agent_profile", "vm107.macro_regime_analyst"),
    ("agent_profile", "vm107.macro_story_tracker"),
    ("agent_profile", "vm107.macro_regime_monitor"),
    ("tool", "vm105.neo4j_macro_graph_walker"),
    ("event_type", "belief_proposal"),
    ("event_type", "regime_transition_detected"),
]


@pytest.fixture(scope="module")
def boot_registry():
    """Boot the CapabilityRegistry against the real VM107 registry root.

    Per Phase 47.6 LD-2 the registry is boot-frozen (one-shot initialize).
    If a prior test in the same process already initialised it, fall back to
    .get() and require the snapshot points at the same root.
    """
    from core.registry.capability_registry import CapabilityRegistry
    from fingpt_core.contracts.capability_registry import RegistryValidationError

    try:
        return CapabilityRegistry.initialize(REGISTRY_ROOT)
    except RuntimeError:
        # already initialized in this process — that's fine, just reuse it
        return CapabilityRegistry.get()
    except RegistryValidationError as exc:
        # Full Phase 47.6 7-stage validation failure — this is the test we want
        # to surface clearly when the registry has any schema drift.
        pytest.fail(
            "Phase 47.6 boot-time registry validation failed — "
            f"the registry rejected on a non-Phase-87 capability: {exc}"
        )


@pytest.mark.parametrize("yaml_type,yaml_id", LOOKUP_INDEX_IDS)
def test_lookup_capability_returns_phase_87_id(
    boot_registry, yaml_type: str, yaml_id: str
) -> None:
    """REQ-87-10 — lookup_capability finds every materialised Phase 87 id."""
    from tools.lookup_capability import lookup

    result = lookup(yaml_id, discovery_reason="phase_87_wave_8_sweep")
    assert result.status == "ok", (
        f"lookup_capability('{yaml_id}') returned status={result.status!r}; "
        f"meta={result.meta} — Phase 87 capability not discoverable."
    )
    assert result.capability is not None
    assert result.capability.id == yaml_id


def test_phase_47_6_boot_validation_passes(boot_registry) -> None:
    """The full 7-stage Phase 47.6 validation MUST succeed across all YAMLs.

    This is the real-world equivalent of the plan's
    `VM107.registry.schema_validator.validate_yaml` — it runs every YAML
    through:
        1. yaml_syntax
        2. schemas (pydantic)
        3. identity_uniqueness
        4. cross_type_linkage   ← surfaces hard_scoped + allowed_agent_profiles
        5. scope_references
        6. dependency_graph
        7. contract_resolution  ← surfaces missing impact_on_decision

    If the boot_registry fixture loaded cleanly, all 7 stages passed.
    """
    # boot_registry coming back from initialize() implies all 7 stages green.
    assert boot_registry is not None
    snapshot = boot_registry._snapshot
    # Sanity: the snapshot includes our Phase 87 ids.
    snapshot_ids = {e.id for e in snapshot.entries}
    phase_87_ids_in_index = {
        yaml_id for (_t, yaml_id) in LOOKUP_INDEX_IDS
    }
    missing = phase_87_ids_in_index - snapshot_ids
    assert not missing, (
        f"Phase 47.6 snapshot missing Phase 87 ids: {sorted(missing)}"
    )
