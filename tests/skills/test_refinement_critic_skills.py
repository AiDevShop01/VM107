"""Phase 48 Plan 06 — 5 family SKILL.md files load + validate via Phase 60 loader.

Each family skill lives at:
    agents/strategy_refinement_critic/skills/<family>-critic/SKILL.md

Frontmatter MUST pass helpers.skills.validate_skill() and carry the locked
Phase 60 + Phase 48 fields (name, description, version, tags,
trigger_patterns, allowed_tools, applies_to_profiles).

Body MUST contain "Family-Specific Evaluation Heuristics" + "Family-Specific
Refinement Targets" sections and be loop-blind.

REQ-48-D1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

from helpers.skills import skill_from_markdown, split_frontmatter, validate_skill


FAMILY_SKILL_IDS = (
    "breakout-critic",
    "mean-reversion-critic",
    "trend-continuation-critic",
    "auction-rotation-critic",
    "volatility-expansion-critic",
)


def _skill_md_path(skill_id: str) -> Path:
    return (
        _VM107_ROOT
        / "agents"
        / "strategy_refinement_critic"
        / "skills"
        / skill_id
        / "SKILL.md"
    )


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_md_file_exists(skill_id):
    """All 5 family SKILL.md files exist on disk."""
    p = _skill_md_path(skill_id)
    assert p.exists(), f"Missing SKILL.md at {p}"


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_md_passes_phase_60_validator(skill_id):
    """Each SKILL.md frontmatter passes helpers.skills.validate_skill()."""
    p = _skill_md_path(skill_id)
    skill = skill_from_markdown(p, include_content=True, validate=False)
    assert skill is not None, f"Frontmatter parse error for {skill_id}"
    issues = validate_skill(skill)
    assert issues == [], f"validate_skill returned issues for {skill_id}: {issues}"
    assert skill.name == skill_id


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_md_frontmatter_fields(skill_id):
    """Frontmatter carries the locked Phase 48 fields."""
    p = _skill_md_path(skill_id)
    fm, _body, errors = split_frontmatter(p.read_text())
    assert errors == [], f"Frontmatter errors for {skill_id}: {errors}"

    # Required fields
    assert fm.get("name") == skill_id
    assert fm.get("version") == "1.0.0"

    tags = fm.get("tags") or []
    assert "critique" in tags
    assert "refinement" in tags
    assert "phase-48" in tags
    # Family-specific tag (matches skill_id prefix)
    family_tag = skill_id.replace("-critic", "")
    assert family_tag in tags

    triggers = (
        fm.get("trigger_patterns")
        or fm.get("triggers")
        or []
    )
    assert isinstance(triggers, list)
    assert len(triggers) >= 2, (
        f"{skill_id} must declare >= 2 trigger_patterns (got {len(triggers)})"
    )

    allowed_tools = fm.get("allowed_tools") or fm.get("allowed-tools") or []
    assert "skills_tool" in allowed_tools
    assert "lookup_capability" in allowed_tools

    profiles = fm.get("applies_to_profiles") or []
    assert "strategy_refinement_critic" in profiles


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_md_body_has_required_sections(skill_id):
    """Body contains the two locked headings + non-empty body."""
    p = _skill_md_path(skill_id)
    _fm, body, _errors = split_frontmatter(p.read_text())
    assert len(body) > 0, f"{skill_id} body is empty"
    assert "Family-Specific Evaluation Heuristics" in body, (
        f"{skill_id} missing 'Family-Specific Evaluation Heuristics' heading"
    )
    assert "Family-Specific Refinement Targets" in body, (
        f"{skill_id} missing 'Family-Specific Refinement Targets' heading"
    )


@pytest.mark.parametrize("skill_id", FAMILY_SKILL_IDS)
def test_skill_md_body_is_loop_blind(skill_id):
    """Body MUST NOT reference loop control (CONTEXT § Decision 1)."""
    p = _skill_md_path(skill_id)
    text = p.read_text().lower()

    banned = [
        r"\biteration\b",
        r"\bmax\s+iterations\b",
        r"\bbudget\b",
        r"\btokens\s+consumed\b",
        r"we're\s+running\s+low",
        r"is\s+this\s+stalling",
        r"\btries\s+left\b",
    ]
    for pat in banned:
        assert not re.search(pat, text), (
            f"Loop-blind violation in {skill_id}: '{pat}' matched"
        )
