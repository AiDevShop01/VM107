"""Phase 58 — VM107 registry: behavioral_pattern YAMLs (5 V1 vocab).

Asserts:
- All 5 V1 behavioral_pattern YAMLs exist + parse + have alias-extended
  frontmatter (Phase 47.6 capability-registry mandate).
- Each YAML's source_metric.field references a real field on Phase 57's
  BehavioralAnalysisResult contract.
- The locked V1 vocab list matches CONTEXT §8 (no add/remove without phase).
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


# Search candidates for the registry root
_REGISTRY_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "registry",
    Path("/Volumes/ HardDrive/FinGPT/VM107/registry"),
    Path("/workspace/VM107/registry"),
]


def _registry_root() -> Path:
    for c in _REGISTRY_CANDIDATES:
        if c.exists():
            return c
    pytest.skip(f"VM107 registry not reachable: {_REGISTRY_CANDIDATES}")


def _load_yaml(path: Path) -> dict:
    if yaml is None:  # pragma: no cover
        pytest.skip("PyYAML not installed in this venv")
    return yaml.safe_load(path.read_text())


# CONTEXT §8 — locked V1 vocab (5 terms; never add to existing YAMLs)
V1_VOCAB = [
    "hesitation",
    "late_entry",
    "over_management",
    "revenge_trade",
    "fomo_entry",
]


# Phase 57 BehavioralAnalysisResult field names that each YAML's
# source_metric.field MUST reference. (cross-checked against
# Dagster/fingpt_core/src/fingpt_core/contracts/analytics/behavioral.py)
PHASE_57_BEHAVIORAL_FIELDS = {
    "hesitation_seconds",
    "late_entry_score",
    "stop_movement_count",
    "over_management_score",
    "revenge_trade_flag",
    "fomo_entry_flag",
}


@pytest.mark.parametrize("pattern_id", V1_VOCAB)
def test_behavioral_pattern_yaml_exists_and_parses(pattern_id):
    """Each V1 behavioral_pattern YAML exists and loads cleanly."""
    root = _registry_root()
    path = root / "behavioral_pattern" / f"{pattern_id}.yaml"
    assert path.exists(), f"Missing behavioral_pattern YAML: {path}"

    data = _load_yaml(path)
    assert isinstance(data, dict), f"YAML at {path} is not a mapping"


@pytest.mark.parametrize("pattern_id", V1_VOCAB)
def test_behavioral_pattern_yaml_alias_extended_frontmatter(pattern_id):
    """Each YAML has alias-extended frontmatter (Phase 47.6 mandate)."""
    root = _registry_root()
    data = _load_yaml(root / "behavioral_pattern" / f"{pattern_id}.yaml")

    # Required alias-extended frontmatter fields
    required = {
        "id",
        "type",
        "status",
        "shipped",
        "last_changed",
        "name",
        "description",
        "category",
        "version",
        "producer",
        "phase",
        "aliases",
        "tags",
        "hard_scoped",
    }
    missing = required - set(data.keys())
    assert not missing, f"{pattern_id}: missing alias-extended fields: {missing}"

    assert data["id"] == pattern_id, (
        f"{pattern_id}: id field {data['id']!r} != filename"
    )
    assert data["type"] == "behavioral_pattern"
    assert data["status"] == "shipped"
    assert data["shipped"] == 58
    assert data["category"] == "behavioral_marker"
    assert data["producer"] == "vm100"
    assert data["phase"] == 58
    assert isinstance(data["aliases"], list)
    assert data["hard_scoped"] is True


@pytest.mark.parametrize("pattern_id", V1_VOCAB)
def test_behavioral_pattern_source_metric_references_phase_57_field(pattern_id):
    """source_metric.field MUST be a real Phase 57 BehavioralAnalysisResult field."""
    root = _registry_root()
    data = _load_yaml(root / "behavioral_pattern" / f"{pattern_id}.yaml")

    sm = data.get("source_metric", {})
    assert "field" in sm, f"{pattern_id}: source_metric.field missing"
    field_name = sm["field"]
    assert field_name in PHASE_57_BEHAVIORAL_FIELDS, (
        f"{pattern_id}: source_metric.field={field_name!r} not in Phase 57 "
        f"BehavioralAnalysisResult fields {PHASE_57_BEHAVIORAL_FIELDS}"
    )


def test_v1_vocab_count_locked():
    """CONTEXT §8 — exactly 5 V1 behavioral_pattern YAMLs ship in Phase 58."""
    root = _registry_root()
    bp_dir = root / "behavioral_pattern"
    yamls = sorted(p.stem for p in bp_dir.glob("*.yaml"))
    assert yamls == sorted(V1_VOCAB), (
        f"behavioral_pattern dir must contain exactly the V1 vocab: "
        f"got {yamls}, expected {sorted(V1_VOCAB)}"
    )
