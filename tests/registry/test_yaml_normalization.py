"""Stage-2-readiness regression test — REG-09.

Validates that every YAML in the capability registry conforms to the LD-3 schema
shape required for Wave 1 loader stage-2 validation to pass on first boot.

Tests:
    test_all_yamls_load            — every YAML parses without exception
    test_status_enum               — every YAML status in {stub,experimental,real,deprecated}
    test_impact_populated          — every YAML impact_on_decision in {HIGH,MEDIUM,LOW}
    test_allowed_profiles_present  — every YAML has allowed_agent_profiles key
    test_skill_md_path_resolves    — every skill YAML skill_md_path resolves to real file
    test_tool_scope_alignment      — tool allowed_agent_profiles superset of HARD_ALLOWED_TOOLS scope

Each test is parametrized so failures identify the exact YAML path at fault.

This test becomes a permanent regression guard. Every future YAML addition must pass it.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Resolve VM107 root and registry root
# ---------------------------------------------------------------------------
_VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Test fixture uses a path fallback (acceptable per pytest conventions).
# Production code (yaml_audit.py, yaml_normalize.py) obeys the no-fallback rule.
REGISTRY_ROOT = pathlib.Path(
    os.environ.get("CAPABILITY_REGISTRY_ROOT") or (_VM107_ROOT / "registry")
)

# FinGPT root: one level above VM107 (used to resolve "VM107/skills/..." paths)
_FINGPT_ROOT = _VM107_ROOT.parent

# Ensure tool_scope is importable
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ---------------------------------------------------------------------------
# YAML loading helpers
# ---------------------------------------------------------------------------

def _collect_yamls() -> list[pathlib.Path]:
    """Return sorted list of all *.yaml files under REGISTRY_ROOT."""
    return sorted(REGISTRY_ROOT.rglob("*.yaml"))


def _load_first_doc(path: pathlib.Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load the first YAML document from path. Returns (data, error_msg)."""
    try:
        raw = path.read_text(encoding="utf-8")
        docs = list(yaml.safe_load_all(raw))
        first = next((d for d in docs if d is not None), None)
        if first is None:
            return None, "empty_document"
        if not isinstance(first, dict):
            return None, f"not_a_mapping: {type(first).__name__}"
        return first, None
    except yaml.YAMLError as exc:
        return None, f"yaml_error: {exc}"


# Collect all YAML paths once at module import (shared across all parametrized tests)
_ALL_YAML_PATHS: list[pathlib.Path] = _collect_yamls()

# IDs for parametrize (registry-relative for clarity)
def _yaml_id(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REGISTRY_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOCKED_STATUS: frozenset[str] = frozenset({"stub", "experimental", "real", "deprecated"})
LOCKED_IMPACT: frozenset[str] = frozenset({"HIGH", "MEDIUM", "LOW"})


# ---------------------------------------------------------------------------
# Test 1: every YAML parses without exception
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("yaml_path", _ALL_YAML_PATHS, ids=[_yaml_id(p) for p in _ALL_YAML_PATHS])
def test_all_yamls_load(yaml_path: pathlib.Path) -> None:
    """REG-09 stage-2 readiness: every YAML normalized to LD-3 schema.

    Every *.yaml under CAPABILITY_REGISTRY_ROOT must parse via yaml.safe_load
    without exception and produce a non-null dict document.
    """
    data, err = _load_first_doc(yaml_path)
    assert err is None, (
        f"{_yaml_id(yaml_path)}: YAML parse error: {err}"
    )
    assert data is not None, f"{_yaml_id(yaml_path)}: document is null/empty"
    assert isinstance(data, dict), f"{_yaml_id(yaml_path)}: document is not a mapping"


# ---------------------------------------------------------------------------
# Test 2: status enum
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("yaml_path", _ALL_YAML_PATHS, ids=[_yaml_id(p) for p in _ALL_YAML_PATHS])
def test_status_enum(yaml_path: pathlib.Path) -> None:
    """REG-09 stage-2 readiness: every YAML normalized to LD-3 schema.

    Every YAML's status field must be in the locked LD-3 enum:
    {stub, experimental, real, deprecated}.
    Zero remaining 'shipped' or 'reserved_for_future' values allowed.
    """
    data, err = _load_first_doc(yaml_path)
    if err:
        pytest.skip(f"parse error (covered by test_all_yamls_load): {err}")

    status = data.get("status")
    assert status in LOCKED_STATUS, (
        f"{_yaml_id(yaml_path)}: status={status!r} is not in locked LD-3 enum "
        f"{sorted(LOCKED_STATUS)}. Legacy values 'shipped' and 'reserved_for_future' "
        f"must be remapped (run yaml_normalize.py --apply)."
    )


# ---------------------------------------------------------------------------
# Test 3: impact_on_decision populated
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("yaml_path", _ALL_YAML_PATHS, ids=[_yaml_id(p) for p in _ALL_YAML_PATHS])
def test_impact_populated(yaml_path: pathlib.Path) -> None:
    """REG-09 stage-2 readiness: every YAML normalized to LD-3 schema.

    Every YAML must have impact_on_decision in {HIGH, MEDIUM, LOW}.
    No 'TODO' placeholder or missing field allowed (hand-curation was completed in
    Plan 47.6-00 Task 2 per CONTEXT.md decision #3 lock).
    """
    data, err = _load_first_doc(yaml_path)
    if err:
        pytest.skip(f"parse error (covered by test_all_yamls_load): {err}")

    impact = data.get("impact_on_decision")
    assert impact in LOCKED_IMPACT, (
        f"{_yaml_id(yaml_path)}: impact_on_decision={impact!r} is not in "
        f"{sorted(LOCKED_IMPACT)}. 'TODO' placeholders must be replaced with "
        f"a hand-curated value before Wave 1 loader can pass stage-2."
    )


# ---------------------------------------------------------------------------
# Test 4: allowed_agent_profiles key present
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("yaml_path", _ALL_YAML_PATHS, ids=[_yaml_id(p) for p in _ALL_YAML_PATHS])
def test_allowed_profiles_present(yaml_path: pathlib.Path) -> None:
    """REG-09 stage-2 readiness: every YAML normalized to LD-3 schema.

    Every YAML must have the key 'allowed_agent_profiles'. Value may be an
    empty list (meaning: no profile restriction — visible to all per stage 5
    semantics), but the key must exist.
    """
    data, err = _load_first_doc(yaml_path)
    if err:
        pytest.skip(f"parse error (covered by test_all_yamls_load): {err}")

    assert "allowed_agent_profiles" in data, (
        f"{_yaml_id(yaml_path)}: 'allowed_agent_profiles' key is missing. "
        f"Run yaml_normalize.py --apply to add defaults."
    )
    profiles = data["allowed_agent_profiles"]
    assert profiles is None or isinstance(profiles, list), (
        f"{_yaml_id(yaml_path)}: 'allowed_agent_profiles' must be a list or null, "
        f"got {type(profiles).__name__}: {profiles!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: skill_md_path resolves for all skill YAMLs
# ---------------------------------------------------------------------------
def _collect_skill_yamls() -> list[pathlib.Path]:
    skill_dir = REGISTRY_ROOT / "skill"
    if not skill_dir.is_dir():
        return []
    return sorted(skill_dir.glob("*.yaml"))


_SKILL_YAML_PATHS = _collect_skill_yamls()


@pytest.mark.parametrize(
    "yaml_path",
    _SKILL_YAML_PATHS,
    ids=[_yaml_id(p) for p in _SKILL_YAML_PATHS],
)
def test_skill_md_path_resolves(yaml_path: pathlib.Path) -> None:
    """REG-09 stage-2 readiness: every YAML normalized to LD-3 schema.

    Every skill/*.yaml must have a 'skill_md_path' field and the referenced
    SKILL.md file must exist on disk.

    skill_md_path is stored as "VM107/skills/<id>/SKILL.md" (repo-relative,
    relative to the FinGPT root one level above VM107).
    """
    data, err = _load_first_doc(yaml_path)
    if err:
        pytest.skip(f"parse error (covered by test_all_yamls_load): {err}")

    assert "skill_md_path" in data, (
        f"{_yaml_id(yaml_path)}: 'skill_md_path' field is missing on skill YAML. "
        f"Add: skill_md_path: VM107/skills/<id>/SKILL.md"
    )
    skill_md_path_str = data["skill_md_path"]
    assert skill_md_path_str, (
        f"{_yaml_id(yaml_path)}: 'skill_md_path' is present but empty."
    )

    # Resolve: "VM107/skills/<id>/SKILL.md" is relative to FinGPT root (_FINGPT_ROOT)
    if skill_md_path_str.startswith("VM107/"):
        # Strip "VM107/" prefix and resolve relative to _VM107_ROOT
        relative = skill_md_path_str[len("VM107/"):]
        resolved = _VM107_ROOT / relative
    else:
        resolved = _FINGPT_ROOT / skill_md_path_str

    assert resolved.exists(), (
        f"{_yaml_id(yaml_path)}: skill_md_path '{skill_md_path_str}' resolved to "
        f"{resolved} — file does not exist on disk. "
        f"Create the SKILL.md file or fix the path."
    )


# ---------------------------------------------------------------------------
# Test 6: tool_scope alignment
# ---------------------------------------------------------------------------
def _collect_tool_yamls() -> list[pathlib.Path]:
    tool_dir = REGISTRY_ROOT / "tool"
    if not tool_dir.is_dir():
        return []
    return sorted(tool_dir.glob("*.yaml"))


_TOOL_YAML_PATHS = _collect_tool_yamls()


@pytest.mark.parametrize(
    "yaml_path",
    _TOOL_YAML_PATHS,
    ids=[_yaml_id(p) for p in _TOOL_YAML_PATHS],
)
def test_tool_scope_alignment(yaml_path: pathlib.Path) -> None:
    """REG-09 stage-2 readiness: every YAML normalized to LD-3 schema.

    For every tool YAML whose id appears in tool_scope.HARD_ALLOWED_TOOLS,
    the YAML's allowed_agent_profiles must be a superset of the scope
    defined in HARD_ALLOWED_TOOLS (catches Pitfall 6 silent scope narrowing).

    HARD_ALLOWED_TOOLS maps agent_id -> frozenset[tool_names_that_agent_can_use].
    This test inverts the mapping: for each tool, find which agents have it in
    their allowed set, then assert the YAML includes all those agents.
    """
    try:
        from core.agents.tool_scope import HARD_ALLOWED_TOOLS
    except ImportError:
        pytest.skip("core.agents.tool_scope not importable — skip scope alignment test")

    data, err = _load_first_doc(yaml_path)
    if err:
        pytest.skip(f"parse error (covered by test_all_yamls_load): {err}")

    tool_id = data.get("id", yaml_path.stem)

    # Build the set of agents that have this tool in their HARD_ALLOWED scope
    required_agents: set[str] = set()
    for agent_id, allowed_tools in HARD_ALLOWED_TOOLS.items():
        if tool_id in allowed_tools:
            required_agents.add(agent_id)

    if not required_agents:
        # Tool is not in any agent's HARD_ALLOWED_TOOLS — no scope constraint
        return

    yaml_profiles = set(data.get("allowed_agent_profiles") or [])
    missing = required_agents - yaml_profiles

    assert not missing, (
        f"{_yaml_id(yaml_path)}: tool '{tool_id}' is in HARD_ALLOWED_TOOLS for agents "
        f"{sorted(required_agents)}, but YAML allowed_agent_profiles is missing: "
        f"{sorted(missing)}. "
        f"The YAML must include all agents that have this tool in their HARD scope "
        f"(or broaden further — narrowing silently breaks runtime authorization)."
    )
