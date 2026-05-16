"""Phase 62-03 Task 2 — test_adaptive_signal_yaml_loads.py

Validates that the three new adaptive signal YAMLs:
  - Are present in registry/signal/
  - Parse cleanly as YAML
  - Contain required schema fields per Phase 47.6 registry manifest
  - Have phase=62
  - Have signal_category set to a known AdaptiveSignalCategory value
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

REGISTRY_SIGNAL = _VM107_ROOT / "registry" / "signal"

_REQUIRED_FIELDS = ["id", "type", "status", "name", "description", "signal_category", "phase"]
_VALID_SIGNAL_CATEGORIES = {
    "STRATEGIC", "BEHAVIORAL", "REGIME", "PATTERN",
    "ADAPTIVE_RECOMMENDATION", "COUNTERFACTUAL_AGGREGATE",
}
_EXPECTED_PHASE_62_IDS = {
    "drift_strategy_category_regime",
    "drift_counterfactual_delta",
    "drift_winrate_calibration",
}


def test_signal_registry_dir_exists():
    """registry/signal/ directory must exist (created by Phase 62-03)."""
    assert REGISTRY_SIGNAL.is_dir(), (
        f"registry/signal/ dir missing at {REGISTRY_SIGNAL}. "
        "Phase 62-03 task 2 must create it."
    )


def test_phase_62_signal_yamls_present():
    """All three Phase 62 signal YAMLs are present."""
    for expected_id in _EXPECTED_PHASE_62_IDS:
        yaml_path = REGISTRY_SIGNAL / f"{expected_id}.yaml"
        assert yaml_path.exists(), (
            f"Expected Phase 62 signal YAML missing: {yaml_path}"
        )


def test_all_signal_yamls_parse():
    """Every signal YAML parses with required fields, type=signal, valid signal_category, phase=62."""
    assert REGISTRY_SIGNAL.is_dir(), f"registry/signal/ missing at {REGISTRY_SIGNAL}"
    yaml_files = sorted(REGISTRY_SIGNAL.glob("*.yaml"))
    assert len(yaml_files) >= 3, (
        f"Expected at least 3 signal YAMLs; found {len(yaml_files)}"
    )
    for yf in yaml_files:
        data = yaml.safe_load(yf.read_text())
        assert isinstance(data, dict), f"{yf} did not parse to dict"
        assert data.get("type") == "signal", (
            f"{yf}: expected type=signal, got {data.get('type')!r}"
        )
        for field in _REQUIRED_FIELDS:
            assert field in data, f"{yf} missing required field: {field!r}"
        signal_cat = data.get("signal_category")
        assert signal_cat in _VALID_SIGNAL_CATEGORIES, (
            f"{yf}: signal_category={signal_cat!r} not in valid set {_VALID_SIGNAL_CATEGORIES}"
        )
        assert data.get("phase") == 62, (
            f"{yf}: expected phase=62, got {data.get('phase')!r}"
        )


@pytest.mark.parametrize("expected_id", sorted(_EXPECTED_PHASE_62_IDS))
def test_each_phase62_signal_has_correct_type_and_category(expected_id):
    """Each Phase 62 signal YAML has type=signal and a valid signal_category."""
    yaml_path = REGISTRY_SIGNAL / f"{expected_id}.yaml"
    if not yaml_path.exists():
        pytest.skip(f"{yaml_path} not found — Phase 62-03 task 2 must create it")
    data = yaml.safe_load(yaml_path.read_text())
    assert data["type"] == "signal"
    assert data["signal_category"] in _VALID_SIGNAL_CATEGORIES
    assert data["phase"] == 62
