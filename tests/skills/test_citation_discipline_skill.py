"""Tests for citation-discipline and narrative-structure SKILL.md files — CTX-§8.

Replaces the Wave 0 skip stub (Plan 60-01) with real test bodies.

CTX-§8: citation-discipline is a constitutional skill — it must be registered,
        parseable, and valid per validate_skill().
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from helpers.skills import validate_skill, discover_skill_md_files, skill_from_markdown

SKILL_PATH = _VM107_ROOT / "skills" / "citation-discipline" / "SKILL.md"


def test_skill_validates_via_validate_skill():
    """CTX-§8 — citation-discipline SKILL.md must pass validate_skill()."""
    assert SKILL_PATH.exists(), f"SKILL.md missing at {SKILL_PATH}"
    skill = skill_from_markdown(SKILL_PATH, validate=False)
    assert skill is not None, "skill_from_markdown returned None — frontmatter parse error"
    issues = validate_skill(skill)
    assert issues == [], f"validate_skill() returned issues: {issues}"
    assert skill.name == "citation-discipline"
    assert "citation" in skill.tags


def test_skill_body_contains_grammar_invariant():
    """citation-discipline body must contain the [ref:...] grammar and all 4 sentence classes."""
    text = SKILL_PATH.read_text()
    assert "[ref:" in text
    assert "ASSERTION" in text
    assert "TRANSITION" in text
    assert "SUMMARY" in text
    assert "META" in text


def test_narrative_structure_skill_also_validates():
    """narrative-structure SKILL.md must also pass validate_skill()."""
    ns_path = SKILL_PATH.parent.parent / "narrative-structure" / "SKILL.md"
    assert ns_path.exists(), f"narrative-structure SKILL.md missing at {ns_path}"
    skill = skill_from_markdown(ns_path, validate=False)
    assert skill is not None, "skill_from_markdown returned None for narrative-structure"
    issues = validate_skill(skill)
    assert issues == [], f"validate_skill() returned issues for narrative-structure: {issues}"
    assert skill.name == "narrative-structure"
