"""Phase 62-03 Task 2 — test_adaptive_discipline_skill_present.py

Validates the adaptive-discipline skill entry and its profile wiring:
  - adaptive-discipline.yaml exists with required fields, phase=62
  - behavioral_mentor_agent.yaml references adaptive-discipline in constitutional_skills (RG-1)
  - weekly_review_agent.yaml references adaptive-discipline in constitutional_skills (RG-1)
  - trade_auditor_agent.yaml does NOT reference adaptive-discipline (per-trade scope isolation)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

REGISTRY_SKILL = _VM107_ROOT / "registry" / "skill"
REGISTRY_PROFILE = _VM107_ROOT / "registry" / "agent_profile"
SKILLS_DIR = _VM107_ROOT / "skills"

_SKILL_ID = "adaptive-discipline"
_SKILL_YAML_PATH = REGISTRY_SKILL / f"{_SKILL_ID}.yaml"
_SKILL_MD_PATH = SKILLS_DIR / _SKILL_ID / "SKILL.md"


def test_adaptive_discipline_yaml_exists():
    """adaptive-discipline.yaml exists in registry/skill/ (RG-1)."""
    assert _SKILL_YAML_PATH.exists(), (
        f"adaptive-discipline.yaml missing at {_SKILL_YAML_PATH}. "
        "Phase 62-03 task 2 must create it."
    )


def test_adaptive_discipline_yaml_has_required_fields():
    """adaptive-discipline.yaml has required fields: id, type, phase, scope, applies_to_profiles."""
    if not _SKILL_YAML_PATH.exists():
        pytest.skip("adaptive-discipline.yaml not found")

    data = yaml.safe_load(_SKILL_YAML_PATH.read_text())
    assert isinstance(data, dict), "adaptive-discipline.yaml must parse to a dict"
    assert data.get("id") == _SKILL_ID
    assert data.get("type") == "skill"
    assert data.get("phase") == 62
    assert data.get("scope") == "constitutional"

    applies_to = data.get("applies_to_profiles", [])
    assert isinstance(applies_to, list)
    assert len(applies_to) >= 1


def test_adaptive_discipline_skill_md_exists():
    """VM107/skills/adaptive-discipline/SKILL.md exists (required by registry/skill test)."""
    assert _SKILL_MD_PATH.exists(), (
        f"SKILL.md missing at {_SKILL_MD_PATH}. "
        "Phase 62-03 must create the skill markdown file."
    )


def test_adaptive_discipline_phase_is_62():
    """adaptive-discipline skill has phase=62."""
    if not _SKILL_YAML_PATH.exists():
        pytest.skip("adaptive-discipline.yaml not found")
    data = yaml.safe_load(_SKILL_YAML_PATH.read_text())
    assert data.get("phase") == 62, (
        f"Expected phase=62, got {data.get('phase')!r}"
    )


def test_behavioral_mentor_has_adaptive_discipline():
    """behavioral_mentor_agent.yaml has adaptive-discipline in constitutional_skills (RG-1)."""
    profile_path = REGISTRY_PROFILE / "behavioral_mentor_agent.yaml"
    assert profile_path.exists(), f"behavioral_mentor_agent.yaml missing at {profile_path}"

    data = yaml.safe_load(profile_path.read_text())
    constitutional = data.get("constitutional_skills", [])
    assert _SKILL_ID in constitutional, (
        f"behavioral_mentor_agent.yaml missing '{_SKILL_ID}' in constitutional_skills. "
        f"Got: {constitutional!r}"
    )


def test_weekly_review_has_adaptive_discipline():
    """weekly_review_agent.yaml has adaptive-discipline in constitutional_skills (RG-1)."""
    profile_path = REGISTRY_PROFILE / "weekly_review_agent.yaml"
    assert profile_path.exists(), f"weekly_review_agent.yaml missing at {profile_path}"

    data = yaml.safe_load(profile_path.read_text())
    constitutional = data.get("constitutional_skills", [])
    assert _SKILL_ID in constitutional, (
        f"weekly_review_agent.yaml missing '{_SKILL_ID}' in constitutional_skills. "
        f"Got: {constitutional!r}"
    )


def test_trade_auditor_does_not_have_adaptive_discipline():
    """trade_auditor_agent.yaml does NOT have adaptive-discipline (per-trade scope isolation).

    Per CTX-DEC-14: trade_auditor has adaptive_signal_categories=[] — it must NOT
    reference adaptive-discipline skill to avoid inadvertently enabling adaptive cognition
    in per-trade analysis.
    """
    profile_path = REGISTRY_PROFILE / "trade_auditor_agent.yaml"
    assert profile_path.exists(), f"trade_auditor_agent.yaml missing at {profile_path}"

    data = yaml.safe_load(profile_path.read_text())
    constitutional = data.get("constitutional_skills", [])
    optional = data.get("optional_skills", [])
    all_skills = constitutional + optional

    assert _SKILL_ID not in all_skills, (
        f"trade_auditor_agent.yaml must NOT reference '{_SKILL_ID}' — "
        f"per-trade scope must not include adaptive cognition. "
        f"Found in skills: {all_skills!r}"
    )


def test_adaptive_discipline_applies_to_behavioral_and_weekly():
    """adaptive-discipline.yaml applies_to_profiles includes behavioral_mentor + weekly_review."""
    if not _SKILL_YAML_PATH.exists():
        pytest.skip("adaptive-discipline.yaml not found")

    data = yaml.safe_load(_SKILL_YAML_PATH.read_text())
    applies_to = set(data.get("applies_to_profiles", []))

    assert "behavioral_mentor_agent" in applies_to, (
        f"adaptive-discipline should apply to behavioral_mentor_agent; got {applies_to!r}"
    )
    assert "weekly_review_agent" in applies_to, (
        f"adaptive-discipline should apply to weekly_review_agent; got {applies_to!r}"
    )


def test_adaptive_signal_categories_in_trade_auditor_is_empty():
    """trade_auditor_agent.yaml has adaptive_signal_categories: [] (CTX-DEC-14)."""
    profile_path = REGISTRY_PROFILE / "trade_auditor_agent.yaml"
    assert profile_path.exists()

    data = yaml.safe_load(profile_path.read_text())
    memory_scope = data.get("memory_scope", {})
    categories = memory_scope.get("adaptive_signal_categories")

    assert categories == [], (
        f"trade_auditor_agent.yaml memory_scope.adaptive_signal_categories must be []. "
        f"Got: {categories!r}"
    )


def test_behavioral_mentor_has_behavioral_in_adaptive_signal_categories():
    """behavioral_mentor_agent.yaml memory_scope.adaptive_signal_categories contains BEHAVIORAL."""
    profile_path = REGISTRY_PROFILE / "behavioral_mentor_agent.yaml"
    assert profile_path.exists()

    data = yaml.safe_load(profile_path.read_text())
    memory_scope = data.get("memory_scope", {})
    categories = set(memory_scope.get("adaptive_signal_categories", []))

    assert "BEHAVIORAL" in categories, (
        f"behavioral_mentor_agent.yaml must have BEHAVIORAL in adaptive_signal_categories. "
        f"Got: {categories!r}"
    )


def test_weekly_review_has_all_six_adaptive_categories():
    """weekly_review_agent.yaml memory_scope.adaptive_signal_categories has all 6 categories."""
    profile_path = REGISTRY_PROFILE / "weekly_review_agent.yaml"
    assert profile_path.exists()

    data = yaml.safe_load(profile_path.read_text())
    memory_scope = data.get("memory_scope", {})
    categories = set(memory_scope.get("adaptive_signal_categories", []))

    expected = {
        "BEHAVIORAL", "STRATEGIC", "REGIME", "PATTERN",
        "ADAPTIVE_RECOMMENDATION", "COUNTERFACTUAL_AGGREGATE",
    }
    assert categories == expected, (
        f"weekly_review_agent.yaml must have all 6 adaptive_signal_categories. "
        f"Expected: {expected!r}\nGot: {categories!r}"
    )
