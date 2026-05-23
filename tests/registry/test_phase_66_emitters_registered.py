"""
RED scaffold for REQ-66-7 — implemented in Plan 66-12.

Tests:
- test_all_5_mandatory_emitter_yamls_exist
- test_3_ancillary_capability_yamls_exist
- test_all_8_yamls_load_and_schema_validate
- test_boot_fail_rule_missing_yaml_identifies_culprit
"""
import pytest
from pathlib import Path

pytestmark = pytest.mark.phase_66

# VM107 root (2 levels up from this test file)
VM107_ROOT = Path(__file__).parents[2]

MANDATORY_YAML_PATHS = [
    VM107_ROOT / "registry" / "tool" / "vm107.narratives.global.yaml",
    VM107_ROOT / "registry" / "tool" / "vm107.opportunities.ranked.yaml",
    VM107_ROOT / "registry" / "tool" / "vm107.intelligence_feed.macro.yaml",
    VM107_ROOT / "registry" / "tool" / "vm107.intelligence_feed.discoveries.yaml",
    VM107_ROOT / "registry" / "event_type" / "vm107.agent_telemetry.yaml",
]

ANCILLARY_YAML_PATHS = [
    VM107_ROOT / "registry" / "tool" / "vm100.ws.mission_control.yaml",
    VM107_ROOT / "registry" / "tool" / "vm102.risk_metrics.snapshot.yaml",
    VM107_ROOT / "registry" / "tool" / "vm100.analytics_calendar.yaml",
    VM107_ROOT / "registry" / "tool" / "vm100.behavioral_edges.for_execution.yaml",
]

ALL_YAML_PATHS = MANDATORY_YAML_PATHS + ANCILLARY_YAML_PATHS


def test_all_5_mandatory_emitter_yamls_exist():
    """REQ-66-7: All 5 mandatory emitter YAML files exist at VM107/registry/<type>/<id>.yaml
    (paths from CONTEXT.md §9)."""
    missing = []
    for yaml_path in MANDATORY_YAML_PATHS:
        if not yaml_path.exists():
            missing.append(str(yaml_path.relative_to(VM107_ROOT)))

    if missing:
        pytest.fail(
            f"REQ-66-7: {len(missing)} mandatory emitter YAML(s) missing (Plan 66-12 must create them):\n"
            + "\n".join(f"  - {p}" for p in missing)
        )


def test_3_ancillary_capability_yamls_exist():
    """REQ-66-7: 3 ancillary capability YAMLs exist:
    vm102.risk_metrics.snapshot, vm100.analytics_calendar, vm100.behavioral_edges.for_execution,
    plus vm100.ws.mission_control."""
    missing = []
    for yaml_path in ANCILLARY_YAML_PATHS:
        if not yaml_path.exists():
            missing.append(str(yaml_path.relative_to(VM107_ROOT)))

    if missing:
        pytest.fail(
            f"REQ-66-7: {len(missing)} ancillary YAML(s) missing (Plan 66-12 must create them):\n"
            + "\n".join(f"  - {p}" for p in missing)
        )


def test_all_8_yamls_load_and_schema_validate():
    """REQ-66-7: All 8 YAMLs load + schema-validate via the existing registry loader (Phase 47.6)."""
    missing = [p for p in ALL_YAML_PATHS if not p.exists()]
    if missing:
        pytest.skip(
            f"Skipping schema-validation — {len(missing)} YAML(s) not yet created (Wave 6 task). "
            "Run again after Plan 66-12 lands all YAMLs."
        )

    try:
        from registry.loader import load_and_validate_yaml
    except ImportError as exc:
        pytest.fail(
            f"Phase 47.6 registry loader must be importable as registry.loader.load_and_validate_yaml: {exc}"
        )

    import yaml
    from registry.loader import load_and_validate_yaml

    failed = []
    for yaml_path in ALL_YAML_PATHS:
        try:
            load_and_validate_yaml(yaml_path)
        except Exception as exc:
            failed.append(f"{yaml_path.name}: {exc}")

    if failed:
        pytest.fail(
            f"REQ-66-7: {len(failed)} YAML(s) failed schema validation:\n"
            + "\n".join(f"  - {f}" for f in failed)
        )


def test_boot_fail_rule_missing_yaml_identifies_culprit():
    """REQ-66-7: Boot-fail rule — if any of the 8 YAMLs missing, assertion error
    identifies WHICH one and WHICH plan should add it."""
    plan_map = {
        "vm107.narratives.global.yaml": "66-12",
        "vm107.opportunities.ranked.yaml": "66-12",
        "vm107.intelligence_feed.macro.yaml": "66-12",
        "vm107.intelligence_feed.discoveries.yaml": "66-12",
        "vm107.agent_telemetry.yaml": "66-12",
        "vm100.ws.mission_control.yaml": "66-12",
        "vm102.risk_metrics.snapshot.yaml": "66-12",
        "vm100.analytics_calendar.yaml": "66-12",
        "vm100.behavioral_edges.for_execution.yaml": "66-12",
    }

    missing = []
    for yaml_path in ALL_YAML_PATHS:
        if not yaml_path.exists():
            responsible_plan = plan_map.get(yaml_path.name, "66-12")
            missing.append(
                f"{yaml_path.name} (Plan {responsible_plan} must create this YAML)"
            )

    if missing:
        # This IS the explanatory failure — tells implementer exactly what to build
        pytest.fail(
            "REQ-66-7 Boot-fail: Missing capability registry YAMLs. "
            "Plan 66-12 must create these before Phase 66 can be considered complete:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
