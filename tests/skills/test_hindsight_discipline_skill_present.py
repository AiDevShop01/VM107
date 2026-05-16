"""Phase 61-01 Wave 0 scaffold — test_hindsight_discipline_skill_present.py

Tests for hindsight-discipline SKILL.md and profile registrations.
Law #10 coverage.

Bodies land in Task 5.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_skill_md_file_exists():
    """VM107/skills/hindsight-discipline/SKILL.md exists on disk."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_skill_registry_yaml_lists_all_3_profiles():
    """VM107/registry/skill/hindsight-discipline.yaml lists all 3 mentor profiles."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_all_3_mentor_profile_yamls_include_hindsight_discipline_in_constitutional_skills():
    """trade_auditor_agent.yaml, behavioral_mentor_agent.yaml, weekly_review_agent.yaml all have hindsight-discipline in constitutional_skills."""
    assert False, "TBD-61-01"
