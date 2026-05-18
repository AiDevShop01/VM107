"""Phase 48 Plan 06 — 5 family-skill registry YAMLs.

Each YAML at VM107/registry/skill/<id>.yaml carries the Phase 47.6 required
shape (id, type=skill, status=real, shipped=48, name, description, version,
phase, applies_to_profiles=[strategy_refinement_critic], allowed_agent_profiles
=[strategy_refinement_critic], location pointing at the SKILL.md on disk,
tags, hard_scoped, impact_on_decision, deprecated).

REQ-48-REG (Phase 47.6 capability registry mandate).
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
import yaml

FAMILY_SKILL_IDS = (
    "breakout-critic",
    "mean-reversion-critic",
    "trend-continuation-critic",
    "auction-rotation-critic",
    "volatility-expansion-critic",
)


def _yaml_path(skill_id: str) -> Path:
    return _VM107_ROOT / "registry" / "skill" / f"{skill_id}.yaml"


def _load_yaml(skill_id: str) -> dict:
    p = _yaml_path(skill_id)
    return yaml.safe_load(p.read_text())


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_yaml_exists(skill_id):
    """Each family-skill registry YAML exists on disk."""
    p = _yaml_path(skill_id)
    assert p.exists(), f"Missing registry YAML at {p}"


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_yaml_required_fields(skill_id):
    """YAML carries the Phase 47.6 required shape."""
    data = _load_yaml(skill_id)
    assert data["id"] == skill_id
    assert data["type"] == "skill"
    assert data["status"] == "real"
    assert data["shipped"] == 48
    assert data["name"] == skill_id
    assert isinstance(data.get("description"), str) and len(data["description"]) > 0
    assert data["version"] == "1.0.0"
    assert data["phase"] == 48
    assert data["producer"] == "VM107"
    assert data["deprecated"] is False


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_yaml_applies_to_strategy_refinement_critic(skill_id):
    """applies_to_profiles + allowed_agent_profiles list the Critic profile."""
    data = _load_yaml(skill_id)
    assert "strategy_refinement_critic" in data["applies_to_profiles"]
    assert "strategy_refinement_critic" in data["allowed_agent_profiles"]


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_yaml_location_points_to_skill_md(skill_id):
    """location.source points at the on-disk SKILL.md."""
    data = _load_yaml(skill_id)
    loc = data["location"]["source"]
    expected_suffix = (
        f"agents/strategy_refinement_critic/skills/{skill_id}/SKILL.md"
    )
    assert loc.endswith(expected_suffix), (
        f"location.source for {skill_id} does not end with {expected_suffix}: {loc}"
    )
    on_disk = _VM107_ROOT / expected_suffix
    assert on_disk.exists(), f"Referenced SKILL.md missing: {on_disk}"


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_yaml_register_capability_directive(skill_id):
    """YAML header contains REGISTER_CAPABILITY directive comment."""
    p = _yaml_path(skill_id)
    text = p.read_text()
    assert "REGISTER_CAPABILITY" in text, (
        f"Missing REGISTER_CAPABILITY directive in {p}"
    )
    assert "type=skill" in text
    assert f"id={skill_id}" in text


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_yaml_tags(skill_id):
    """Tags include phase-48 + critique + refinement + family-specific tag."""
    data = _load_yaml(skill_id)
    tags = data["tags"]
    assert "phase-48" in tags
    assert "critique" in tags
    assert "refinement" in tags
    family_tag = skill_id.replace("-critic", "")
    assert family_tag in tags
