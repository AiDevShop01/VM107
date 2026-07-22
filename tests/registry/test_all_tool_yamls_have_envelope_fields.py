"""Production tool YAML regression test: all 53 entries carry Phase 70.5 envelope-provenance fields.

Tests:
    1. Exactly 53 tool YAML files exist in VM107/registry/tool/ (guard against accidental deletion).
    2. Every tool YAML has all 4 envelope-provenance fields with valid values:
         - typical_confidence: float in [0.0, 1.0]
         - expected_freshness_seconds: int >= 0
         - is_deterministic: bool
         - version: str matching \\d+\\.\\d+(\\.\\d+)?
    3. Reports ALL failures in a single assertion (not just the first) so a single run
       gives the complete picture for any migration regression.

Design:
    - Loads YAMLs directly (not via run_full_pipeline) so this test is fast and
      independent of Stages 1-7 validation side-effects.
    - Uses an accumulate-then-fail pattern: all files are checked, all failures
      collected, then one compound assertion fails with the full list.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

TOOL_YAML_DIR = Path(__file__).resolve().parents[2] / "registry" / "tool"
EXPECTED_TOOL_COUNT = 82  # Phase 103.4 Plan 02: +6 SIW AI consumer YAMLs (additive delta).
# NOTE: the prior literal (55, Phase 83 Plan 12) was stale — the tool/ dir had already
# drifted to 76 files via Phases 85-96 (macro/research tools added without updating this
# constant). This bump reconciles the true baseline (76) + the +6 Phase-103.4 consumers = 82.
SEMVER_LITE_PATTERN = re.compile(r"^\d+\.\d+(\.\d+)?$")


def test_tool_yaml_count_is_exactly_53():
    """Guard against accidental deletion: registry/tool/ must have exactly 53 YAML files."""
    yaml_files = sorted(TOOL_YAML_DIR.glob("*.yaml"))
    assert len(yaml_files) == EXPECTED_TOOL_COUNT, (
        f"Expected exactly {EXPECTED_TOOL_COUNT} tool YAML files in {TOOL_YAML_DIR}, "
        f"found {len(yaml_files)}. "
        f"Files: {[f.name for f in yaml_files]}"
    )


def test_all_tool_yamls_have_valid_envelope_fields():
    """Every tool YAML must have all 4 Phase 70.5 envelope-provenance fields with valid values.

    Accumulates ALL failures before reporting — a single run surfaces every missing/invalid field.
    """
    yaml_files = sorted(TOOL_YAML_DIR.glob("*.yaml"))
    failures: list[str] = []

    for yaml_file in yaml_files:
        try:
            raw = yaml.safe_load(yaml_file.read_text())
        except yaml.YAMLError as exc:
            failures.append(f"{yaml_file.name}: YAML parse error — {exc}")
            continue

        if not isinstance(raw, dict):
            failures.append(f"{yaml_file.name}: not a YAML mapping")
            continue

        name = yaml_file.name

        # --- typical_confidence ---
        if "typical_confidence" not in raw:
            failures.append(f"{name}: missing 'typical_confidence'")
        else:
            tc = raw["typical_confidence"]
            if not isinstance(tc, (int, float)):
                failures.append(f"{name}: 'typical_confidence' must be a float, got {type(tc).__name__!r} ({tc!r})")
            elif not (0.0 <= float(tc) <= 1.0):
                failures.append(f"{name}: 'typical_confidence' {tc!r} is outside [0.0, 1.0]")

        # --- expected_freshness_seconds ---
        if "expected_freshness_seconds" not in raw:
            failures.append(f"{name}: missing 'expected_freshness_seconds'")
        else:
            efs = raw["expected_freshness_seconds"]
            if not isinstance(efs, int):
                failures.append(f"{name}: 'expected_freshness_seconds' must be an int, got {type(efs).__name__!r} ({efs!r})")
            elif efs < 0:
                failures.append(f"{name}: 'expected_freshness_seconds' {efs!r} is negative")

        # --- is_deterministic ---
        if "is_deterministic" not in raw:
            failures.append(f"{name}: missing 'is_deterministic'")
        else:
            isd = raw["is_deterministic"]
            if not isinstance(isd, bool):
                failures.append(f"{name}: 'is_deterministic' must be a bool, got {type(isd).__name__!r} ({isd!r})")

        # --- version ---
        if "version" not in raw:
            failures.append(f"{name}: missing 'version'")
        else:
            ver = raw["version"]
            if not isinstance(ver, str):
                failures.append(f"{name}: 'version' must be a string, got {type(ver).__name__!r} ({ver!r})")
            elif not SEMVER_LITE_PATTERN.match(str(ver).strip()):
                failures.append(
                    f"{name}: 'version' {ver!r} does not match semver-lite format "
                    f"('\\d+\\.\\d+' or '\\d+\\.\\d+\\.\\d+')"
                )

    if failures:
        failure_list = "\n  - ".join(failures)
        assert False, (
            f"Phase 70.5 envelope-provenance field validation failed for "
            f"{len(failures)} tool YAML(s):\n  - {failure_list}\n\n"
            f"Every tool YAML in {TOOL_YAML_DIR} must declare all 4 fields with valid values. "
            f"See .planning/HOW-TO-ADD-TOOLS.md §0.5 for field semantics."
        )


def test_pilot_tools_have_plan06_exercise_values():
    """Pilot tools (get_trade_context, behavioral_analysis_tool, execution_quality_tool) must
    have the specific author-judgment values that Plan 06 integration tests will exercise.

    This test locks the committed values so accidental edits are immediately caught.
    """
    pilot_specs = {
        "get_trade_context.yaml": {
            "typical_confidence": 0.85,
            "expected_freshness_seconds": 60,
            "is_deterministic": True,
            "version": "1.1.0",
        },
        "behavioral_analysis_tool.yaml": {
            "typical_confidence": 0.75,
            "expected_freshness_seconds": 60,
            "is_deterministic": True,
            # version: 1.0.0 (flexible — just check it exists and is valid semver)
        },
        "execution_quality_tool.yaml": {
            "typical_confidence": 0.80,
            "expected_freshness_seconds": 30,
            "is_deterministic": True,
        },
    }

    failures: list[str] = []

    for filename, expected_fields in pilot_specs.items():
        yaml_file = TOOL_YAML_DIR / filename
        if not yaml_file.exists():
            failures.append(f"{filename}: file not found")
            continue

        raw = yaml.safe_load(yaml_file.read_text())

        for field, expected_value in expected_fields.items():
            actual = raw.get(field)
            if actual != expected_value:
                failures.append(
                    f"{filename}: '{field}' expected {expected_value!r}, got {actual!r}. "
                    f"Plan 06 integration tests depend on this value — do not change without "
                    f"updating the Plan 06 test expectations."
                )

    if failures:
        failure_list = "\n  - ".join(failures)
        assert False, (
            f"Pilot tool envelope-provenance value regression:\n  - {failure_list}"
        )
