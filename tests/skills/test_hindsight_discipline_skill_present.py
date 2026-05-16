"""Phase 61-01 Task 5 — test_hindsight_discipline_skill_present.py

Tests for hindsight-discipline SKILL.md and profile registrations.
Law #10 coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# VM107 root setup
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_SKILL_MD = _VM107_ROOT / "skills" / "hindsight-discipline" / "SKILL.md"
_SKILL_YAML = _VM107_ROOT / "registry" / "skill" / "hindsight-discipline.yaml"
_MENTOR_PROFILES = [
    _VM107_ROOT / "registry" / "agent_profile" / "trade_auditor_agent.yaml",
    _VM107_ROOT / "registry" / "agent_profile" / "behavioral_mentor_agent.yaml",
    _VM107_ROOT / "registry" / "agent_profile" / "weekly_review_agent.yaml",
]


def test_skill_md_file_exists():
    """VM107/skills/hindsight-discipline/SKILL.md exists on disk."""
    assert _SKILL_MD.exists(), f"SKILL.md not found at {_SKILL_MD}"
    content = _SKILL_MD.read_text()
    assert len(content) >= 40 * 60, (  # ~40+ lines min
        f"SKILL.md too short ({len(content)} chars); expected substantive content"
    )
    # Verify it contains the three prohibited framings section
    assert "Prohibited" in content or "prohibited" in content, (
        "SKILL.md must document prohibited framings"
    )


def test_skill_registry_yaml_lists_all_3_profiles():
    """VM107/registry/skill/hindsight-discipline.yaml lists all 3 mentor profiles."""
    assert _SKILL_YAML.exists(), f"Skill registry YAML not found at {_SKILL_YAML}"
    data = yaml.safe_load(_SKILL_YAML.read_text())
    assert isinstance(data, dict), "Skill YAML must be a dict"

    applies_to = data.get("applies_to_profiles", [])
    expected_profiles = {"trade_auditor_agent", "behavioral_mentor_agent", "weekly_review_agent"}
    registered = set(applies_to)

    missing = expected_profiles - registered
    assert not missing, (
        f"hindsight-discipline.yaml missing profiles: {missing}. "
        f"Found: {registered}"
    )


def test_all_3_mentor_profile_yamls_include_hindsight_discipline_in_constitutional_skills():
    """trade_auditor_agent.yaml, behavioral_mentor_agent.yaml, weekly_review_agent.yaml
    all have 'hindsight-discipline' in constitutional_skills."""
    for profile_path in _MENTOR_PROFILES:
        assert profile_path.exists(), f"Mentor profile YAML not found: {profile_path}"
        data = yaml.safe_load(profile_path.read_text())
        constitutional_skills = data.get("constitutional_skills", [])
        assert "hindsight-discipline" in constitutional_skills, (
            f"{profile_path.name} missing 'hindsight-discipline' in constitutional_skills. "
            f"Found: {constitutional_skills}. Law #10: hindsight-discipline MANDATORY for all mentor profiles."
        )
