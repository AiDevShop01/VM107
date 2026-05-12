"""Tests for Phase 60 skill registry YAMLs — CTX-§13.

Replaces the Wave 0 skip stub (Plan 60-01) with real test bodies.

CTX-§13: All new registry/skill/ YAMLs must exist, parse cleanly with required fields,
and skill_md_path values must point to real SKILL.md files on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import yaml

REGISTRY_SKILL = _VM107_ROOT / "registry" / "skill"


def _resolve_skill_md_path(skill_md_path_str: str) -> Path:
    """Resolve a skill_md_path value (repo-relative "VM107/skills/...") to an absolute path."""
    # skill_md_path is stored as "VM107/skills/<name>/SKILL.md" (repo-relative)
    # The repo root is _VM107_ROOT.parent if VM107 is a subdirectory,
    # or _VM107_ROOT directly if the path starts with "VM107/".
    if skill_md_path_str.startswith("VM107/"):
        # Strip "VM107/" prefix and resolve relative to _VM107_ROOT
        relative = skill_md_path_str[len("VM107/"):]
        return _VM107_ROOT / relative
    # Fall back: try as relative to VM107 root directly
    return _VM107_ROOT / skill_md_path_str


def test_all_skill_yamls_parse():
    """CTX-§13 — every skill YAML parses with required fields + skill_md_path exists."""
    assert REGISTRY_SKILL.is_dir(), f"registry/skill/ directory missing at {REGISTRY_SKILL}"
    yaml_files = sorted(REGISTRY_SKILL.glob("*.yaml"))
    assert len(yaml_files) >= 2, (
        f"Expected at least 2 skill YAMLs (citation-discipline + narrative-structure); found {len(yaml_files)}"
    )
    for yf in yaml_files:
        data = yaml.safe_load(yf.read_text())
        assert isinstance(data, dict), f"{yf} did not parse to dict"
        assert data.get("type") == "skill", f"{yf}: expected type=skill, got {data.get('type')!r}"
        for required in [
            "id", "name", "description", "version", "phase", "status",
            "scope", "applies_to_profiles", "skill_md_path",
        ]:
            assert required in data, f"{yf} missing required field: {required}"
        assert data["scope"] in ("constitutional", "optional"), (
            f"{yf}: scope must be 'constitutional' or 'optional', got {data['scope']!r}"
        )
        # skill_md_path is repo-relative; verify the SKILL.md file exists on disk
        md_path = _resolve_skill_md_path(data["skill_md_path"])
        assert md_path.exists(), (
            f"{yf}: skill_md_path '{data['skill_md_path']}' resolved to {md_path} — file not found"
        )


def test_citation_discipline_is_shared_constitutional():
    """Directive #3 — citation-discipline is ONE shared entry (not 3 duplicates), scope=constitutional."""
    cd_path = REGISTRY_SKILL / "citation-discipline.yaml"
    assert cd_path.exists(), f"citation-discipline.yaml not found at {cd_path}"
    data = yaml.safe_load(cd_path.read_text())
    assert data["scope"] == "constitutional"
    # Directive #3 — ONE shared entry, all 3 profiles listed together
    assert set(data["applies_to_profiles"]) == {
        "trade_auditor_agent", "behavioral_mentor_agent", "weekly_review_agent"
    }, (
        f"citation-discipline.yaml applies_to_profiles must list all 3 Phase 60 profiles; got {data['applies_to_profiles']}"
    )
