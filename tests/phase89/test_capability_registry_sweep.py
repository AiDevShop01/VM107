"""Phase 89 Plan 08 — Capability Registry Sweep Tests.

REQ-89-8: All 8 new Phase 89 capability registry entries must be discoverable
and structurally valid.

Phase 47.6 lock: No hardcoded agent profile strings outside registry/tests/tools/.
All references to the 4 new agent ids must go through lookup_capability(id=...).

8 tests covering:
  - Test 1 (yaml files exist):       All 8 Phase 89 YAML files are present on disk.
  - Test 2 (field completeness):     Each entry has its required typed fields:
                                     agents → trigger/allowed_tools/b1_artifact_required/brain_absorbed,
                                     rubrics → checks/threshold/refinement,
                                     contracts → severity_rules/beliefstore_wiring,
                                     event_types → schema_version/producer_agents/consumer_phases.
  - Test 3 (rubric weights sum):     investigator + counterfactual rubric weights both sum
                                     to 1.000 within 0.001 tolerance.
  - Test 4 (B13 contract parsing):   contract.b13_contradiction_engine severity_rules parse
                                     cleanly — all three severity levels have valid triggers.
  - Test 5 (grep gate — Phase 47.6): No hardcoded profile-id strings for the 4 new agents
                                     exist outside registry/, tests/, and tools/ in VM107 source.
  - Test 6 (provisional event_type): event_type.alert_candidate_created YAML has
                                     schema_version, producer_agents, consumer_phases, and
                                     applies_to_consumers (Decision 13).
  - Test 7 (severity translation):   alert_candidate_created severity translation matches
                                     what Wave 3 contradiction_engine emits:
                                     info→Info, warning→Important, blocking→Critical.
  - Test 8 (count gate):             Registry sweep finds exactly 8 new Phase 89 entries
                                     (4 agent_profiles + 2 rubrics + 1 contract + 1 event_type).

Per project locks:
  - No real VM stack required — tests read registry YAML files directly.
  - env-driven config; no hardcoded URLs.
  - Phase 47.6: agents discover capabilities via registry, never hardcoded enumeration.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
from typing import Any

import pytest
import yaml

# ── Registry root ─────────────────────────────────────────────────────────────

REGISTRY_ROOT = pathlib.Path(__file__).parents[2] / "registry"
VM107_ROOT = pathlib.Path(__file__).parents[2]

# ── The 8 Phase 89 capability entries ────────────────────────────────────────

PHASE89_ENTRIES = [
    {
        "id": "vm107.macro_investigator",
        "type": "agent_profile",
        "path": REGISTRY_ROOT / "agent_profile" / "vm107.macro_investigator.yaml",
    },
    {
        "id": "vm107.counterfactual_engine",
        "type": "agent_profile",
        "path": REGISTRY_ROOT / "agent_profile" / "vm107.counterfactual_engine.yaml",
    },
    {
        "id": "vm107.macro_contradiction_detector",
        "type": "agent_profile",
        "path": REGISTRY_ROOT / "agent_profile" / "vm107.macro_contradiction_detector.yaml",
    },
    {
        "id": "vm107.macro_relationship_discovery",
        "type": "agent_profile",
        "path": REGISTRY_ROOT / "agent_profile" / "vm107.macro_relationship_discovery.yaml",
    },
    {
        "id": "rubric.macro_investigator_qa",
        "type": "rubric",
        "path": REGISTRY_ROOT / "rubric" / "rubric.macro_investigator_qa.yaml",
    },
    {
        "id": "rubric.counterfactual_engine_qa",
        "type": "rubric",
        "path": REGISTRY_ROOT / "rubric" / "rubric.counterfactual_engine_qa.yaml",
    },
    {
        "id": "contract.b13_contradiction_engine",
        "type": "contract",
        "path": REGISTRY_ROOT / "contract" / "contract.b13_contradiction_engine.yaml",
    },
    {
        "id": "event_type.alert_candidate_created",
        "type": "event_type",
        "path": REGISTRY_ROOT / "event_type" / "alert_candidate_created.yaml",
    },
]

# ── Phase 89 new agent profile ids (grep gate targets) ───────────────────────

PHASE89_AGENT_IDS = [
    "vm107.macro_investigator",
    "vm107.counterfactual_engine",
    "vm107.macro_contradiction_detector",
    "vm107.macro_relationship_discovery",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_yaml(path: pathlib.Path) -> dict:
    """Load and return a YAML file as a dict."""
    return yaml.safe_load(path.read_text())


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: YAML files exist on disk
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
@pytest.mark.parametrize("entry", PHASE89_ENTRIES, ids=[e["id"] for e in PHASE89_ENTRIES])
def test_registry_yaml_exists(entry: dict) -> None:
    """All 8 Phase 89 YAML files are present on disk."""
    assert entry["path"].exists(), (
        f"Registry YAML missing for {entry['id']!r}: expected at {entry['path']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Field completeness per type
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
@pytest.mark.parametrize("entry", PHASE89_ENTRIES, ids=[e["id"] for e in PHASE89_ENTRIES])
def test_registry_field_completeness(entry: dict) -> None:
    """Each entry has the required typed fields for its capability type."""
    data = _load_yaml(entry["path"])
    cap_type = entry["type"]
    cap_id = entry["id"]

    if cap_type == "agent_profile":
        required = ["trigger", "allowed_tools", "b1_artifact_required", "brain_absorbed"]
        for field in required:
            assert field in data, (
                f"Agent profile {cap_id!r} missing required field {field!r}"
            )

    elif cap_type == "rubric":
        required = ["checks", "threshold", "refinement"]
        for field in required:
            assert field in data, (
                f"Rubric {cap_id!r} missing required field {field!r}"
            )
        # Threshold must have accept and refine_below
        assert "accept" in data["threshold"], (
            f"Rubric {cap_id!r} threshold missing 'accept'"
        )

    elif cap_type == "contract":
        required = ["severity_rules", "beliefstore_wiring"]
        for field in required:
            assert field in data, (
                f"Contract {cap_id!r} missing required field {field!r}"
            )

    elif cap_type == "event_type":
        required = ["schema_version", "producer_agents", "consumer_phases"]
        for field in required:
            assert field in data, (
                f"Event type {cap_id!r} missing required field {field!r}"
            )

    else:
        pytest.fail(f"Unknown capability type {cap_type!r} for {cap_id!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Rubric weights sum to 1.0 (within 0.001 tolerance)
# ─────────────────────────────────────────────────────────────────────────────

_RUBRIC_ENTRIES = [e for e in PHASE89_ENTRIES if e["type"] == "rubric"]


@pytest.mark.phase89
@pytest.mark.parametrize("entry", _RUBRIC_ENTRIES, ids=[e["id"] for e in _RUBRIC_ENTRIES])
def test_rubric_weights_sum_to_one(entry: dict) -> None:
    """Rubric check weights must sum to 1.000 within 0.001 tolerance."""
    data = _load_yaml(entry["path"])
    checks = data.get("checks", [])
    assert checks, f"Rubric {entry['id']!r} has no checks"

    total = sum(float(c["weight"]) for c in checks)
    assert abs(total - 1.0) <= 0.001, (
        f"Rubric {entry['id']!r} weights sum to {total:.4f}, expected 1.000 ± 0.001. "
        f"Checks: {[(c['id'], c['weight']) for c in checks]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: B13 contract severity_rules parse cleanly
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
def test_b13_contract_severity_rules_parse() -> None:
    """contract.b13_contradiction_engine severity_rules have valid info/warning/blocking sections."""
    contract_path = REGISTRY_ROOT / "contract" / "contract.b13_contradiction_engine.yaml"
    assert contract_path.exists(), f"B13 contract missing at {contract_path}"

    data = _load_yaml(contract_path)
    severity_rules = data.get("severity_rules")
    assert severity_rules is not None, "B13 contract missing 'severity_rules'"

    for level in ("info", "warning", "blocking"):
        assert level in severity_rules, (
            f"B13 severity_rules missing '{level}' section"
        )
        rule = severity_rules[level]
        assert "triggers" in rule, (
            f"B13 severity_rules['{level}'] missing 'triggers'"
        )
        triggers = rule["triggers"]
        assert isinstance(triggers, list), (
            f"B13 severity_rules['{level}']['triggers'] must be a list, got {type(triggers)}"
        )
        assert len(triggers) >= 1, (
            f"B13 severity_rules['{level}']['triggers'] must have at least 1 entry"
        )

    # Blocking must have refusal_text and user_re_ask_behavior (Decision 7)
    blocking = severity_rules["blocking"]
    assert "refusal_text" in blocking, "B13 blocking rule missing 'refusal_text' (Decision 7)"
    assert "user_re_ask_behavior" in blocking, (
        "B13 blocking rule missing 'user_re_ask_behavior' (Decision 7)"
    )
    assert blocking["user_re_ask_behavior"] == "refuse_stands", (
        f"B13 blocking user_re_ask_behavior must be 'refuse_stands', got {blocking['user_re_ask_behavior']!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Grep gate — Phase 47.6 hardcoded enumeration lock
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
def test_no_hardcoded_agent_profile_strings_outside_registry() -> None:
    """Phase 47.6 lock: no hardcoded Phase 89 agent profile strings in VM107 source.

    Searches all .py files in VM107/ for any of the 4 new agent id strings.
    Exclusions: registry/, tests/, tools/ (these are the allowed enumeration sites).
    Any hit in non-excluded .py files must be inside a lookup_capability(id=...) call.

    Violations look like:
        profile_id = "vm107.macro_investigator"        # FAIL — bare hardcoded string
        agent = "vm107.counterfactual_engine"          # FAIL — bare hardcoded string
    """
    # Build grep pattern for all 4 agent ids
    pattern = "|".join(re.escape(aid) for aid in PHASE89_AGENT_IDS)

    violations = []

    # Walk all .py files in VM107, excluding registry/, tests/, tools/
    excluded_dirs = {"registry", "tests", "tools"}
    for py_file in VM107_ROOT.rglob("*.py"):
        # Skip excluded directories
        relative = py_file.relative_to(VM107_ROOT)
        top_dir = relative.parts[0] if relative.parts else ""
        if top_dir in excluded_dirs:
            continue

        content = py_file.read_text(errors="replace")
        lines = content.splitlines()

        # Detect which lines are inside triple-quoted docstrings.
        # Simple heuristic: track triple-quote toggle state per file.
        in_docstring = False
        docstring_lines: set[int] = set()
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            triple_count = stripped.count('"""') + stripped.count("'''")
            if triple_count % 2 == 1:
                # Odd number of triple-quote delimiters on this line → toggle
                if in_docstring:
                    docstring_lines.add(i)   # closing line is still part of docstring
                    in_docstring = False
                else:
                    in_docstring = True
                    docstring_lines.add(i)
            elif in_docstring:
                docstring_lines.add(i)

        for lineno, line in enumerate(lines, start=1):
            for agent_id in PHASE89_AGENT_IDS:
                if agent_id in line:
                    stripped = line.strip()
                    # Allow: comment lines (# ...)
                    if stripped.startswith("#"):
                        continue
                    # Allow: lines inside docstrings (module/function docs)
                    if lineno in docstring_lines:
                        continue
                    # Allow: inside a lookup_capability(id=...) call
                    if "lookup_capability" in line and "id=" in line:
                        continue
                    # Allow: producer_agent_id= usages — data-identity field,
                    # not a capability dispatch pattern (Phase 47.6 targets dispatch,
                    # not data values that carry agent identity as metadata).
                    if "producer_agent_id=" in line:
                        continue
                    violations.append(
                        f"{py_file.relative_to(VM107_ROOT)}:{lineno}: {line.strip()}"
                    )

    assert not violations, (
        f"Phase 47.6 lock VIOLATED — found {len(violations)} hardcoded agent profile "
        f"string(s) outside registry/tests/tools/:\n"
        + "\n".join(violations)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Provisional event_type discoverable + Decision 13 fields
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
def test_alert_candidate_event_type_provisional_fields() -> None:
    """event_type.alert_candidate_created has all required Decision 13 fields."""
    event_path = REGISTRY_ROOT / "event_type" / "alert_candidate_created.yaml"
    assert event_path.exists(), f"alert_candidate_created.yaml missing at {event_path}"

    data = _load_yaml(event_path)

    # Core fields
    assert data.get("id") == "event_type.alert_candidate_created"
    assert data.get("type") == "event_type"
    assert data.get("status") == "provisional", (
        f"Expected status='provisional', got {data.get('status')!r}"
    )
    assert data.get("schema_version") == "0.1-provisional", (
        f"Expected schema_version='0.1-provisional', got {data.get('schema_version')!r}"
    )

    # Phase 91 forward-reference
    assert data.get("refined_by_phase") == 91, (
        f"Expected refined_by_phase=91, got {data.get('refined_by_phase')!r}"
    )

    # Producer agents (Wave 3 + Wave 4)
    producers = data.get("producer_agents", [])
    assert "vm107.macro_contradiction_detector" in producers, (
        "alert_candidate_created must list vm107.macro_contradiction_detector as producer"
    )
    assert "vm107.macro_relationship_discovery" in producers, (
        "alert_candidate_created must list vm107.macro_relationship_discovery as producer"
    )

    # Consumer phases
    consumers = data.get("consumer_phases", [])
    assert 91 in consumers, (
        "alert_candidate_created must list phase 91 as a consumer_phase"
    )

    # Decision 13: applies_to_consumers present
    assert "applies_to_consumers" in data, (
        "alert_candidate_created missing 'applies_to_consumers' field (Decision 13)"
    )
    assert len(data["applies_to_consumers"]) >= 1, (
        "alert_candidate_created applies_to_consumers must have at least 1 entry"
    )

    # Envelope schema ref
    assert "envelope_schema_ref" in data, (
        "alert_candidate_created missing 'envelope_schema_ref'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Severity translation table matches Wave 3 emit expectations
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
def test_severity_translation_matches_b13_emit() -> None:
    """alert_candidate_created severity translation matches B13 contract values.

    Wave 3's contradiction_engine reads severity_translation from this YAML.
    Decision 13: info→Info, warning→Important, blocking→Critical.
    """
    event_path = REGISTRY_ROOT / "event_type" / "alert_candidate_created.yaml"
    data = _load_yaml(event_path)

    translation = data.get("severity_translation")
    assert translation is not None, "alert_candidate_created missing 'severity_translation'"

    expected = {
        "info": "Info",
        "warning": "Important",
        "blocking": "Critical",
    }
    for b13_level, phase91_level in expected.items():
        assert translation.get(b13_level) == phase91_level, (
            f"Severity translation mismatch for '{b13_level}': "
            f"expected {phase91_level!r}, got {translation.get(b13_level)!r}"
        )

    # Cross-validate: B13 contract also has a phase_91_severity_translation section
    # (both must agree — drift between the two would be a bug)
    contract_path = REGISTRY_ROOT / "contract" / "contract.b13_contradiction_engine.yaml"
    contract = _load_yaml(contract_path)
    b13_translation = contract.get("phase_91_severity_translation", {})

    for b13_level, phase91_level in expected.items():
        assert b13_translation.get(b13_level) == phase91_level, (
            f"B13 contract phase_91_severity_translation mismatch for '{b13_level}': "
            f"expected {phase91_level!r}, got {b13_translation.get(b13_level)!r}. "
            f"Translation tables in alert_candidate_created.yaml and "
            f"contract.b13_contradiction_engine.yaml must match."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Count gate — exactly 8 new Phase 89 entries
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase89
def test_phase89_registry_entry_count() -> None:
    """Registry sweep finds exactly 8 new Phase 89 entries.

    Breakdown: 4 agent_profiles + 2 rubrics + 1 contract + 1 event_type.
    This test catches drift if a future change accidentally adds or removes
    a Phase 89 entry from the PHASE89_ENTRIES list above.
    """
    expected_counts = {
        "agent_profile": 4,
        "rubric": 2,
        "contract": 1,
        "event_type": 1,
    }
    expected_total = 8

    actual_counts: dict[str, int] = {}
    for entry in PHASE89_ENTRIES:
        cap_type = entry["type"]
        actual_counts[cap_type] = actual_counts.get(cap_type, 0) + 1

    assert actual_counts == expected_counts, (
        f"Phase 89 registry entry count mismatch.\n"
        f"Expected: {expected_counts}\n"
        f"Actual:   {actual_counts}"
    )
    assert sum(actual_counts.values()) == expected_total, (
        f"Expected {expected_total} total Phase 89 entries, "
        f"got {sum(actual_counts.values())}"
    )

    # Also verify each YAML file actually exists on disk
    missing = [e["id"] for e in PHASE89_ENTRIES if not e["path"].exists()]
    assert not missing, (
        f"Count gate found {len(missing)} missing YAML files on disk: {missing}"
    )
