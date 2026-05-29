"""Phase 71 Wave 2 — GREEN tests for `conversation_mode` registry YAMLs.

Plan 03 ships the 6 `conversation_mode` YAML entries under
`VM107/registry/conversation_mode/`. These tests flipped RED -> GREEN.

Expected YAML schema per RESEARCH.md Pattern 8:
- id: string (matches filename stem)
- type: "conversation_mode"
- status: real | planned | deprecated
- shipped: phase number (e.g., 71)
- host_agent_profile: agent profile id (must resolve to an agent_profile YAML)
- system_prompt_path: path under VM107/agents/...
- allowed_tools: list[str] (tool capability ids)

REQ-71-7.

Conversation modes (CONTEXT.md Decision 4 hybrid 4c):
  pre_trade, macro_chat, execution_chat, reflection_chat, research_chat, strategy_chat
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# chat.py reads CHAT_MODEL at import time; the validator pipeline does NOT
# touch chat.py but the singleton test below imports core.registry which
# indirectly forces a few module loads. Stub for safety (matches Plan 02
# pattern in test_chat_conversation_type.py).
os.environ.setdefault("CHAT_MODEL", "test-model")

EXPECTED_MODES = (
    "pre_trade",
    "macro_chat",
    "execution_chat",
    "reflection_chat",
    "research_chat",
    "strategy_chat",
)

REQUIRED_FIELDS = (
    "id",
    "type",
    "status",
    "shipped",
    "host_agent_profile",
    "system_prompt_path",
    "allowed_tools",
)


def _conversation_mode_dir() -> Path:
    return _VM107_ROOT / "registry" / "conversation_mode"


def _yaml_path(mode_id: str) -> Path:
    return _conversation_mode_dir() / f"{mode_id}.yaml"


def test_all_6_conversation_modes_exist():
    """Each of the 6 conversation modes must have a YAML file on disk."""
    d = _conversation_mode_dir()
    assert d.exists(), f"Plan 03 must create directory {d}"
    files = sorted(p.stem for p in d.glob("*.yaml"))
    for mode in EXPECTED_MODES:
        assert mode in files, f"Missing YAML for conversation mode: {mode}"


@pytest.mark.parametrize("mode_id", EXPECTED_MODES)
def test_conversation_mode_schema_validates(mode_id):
    """Each YAML must carry the Phase 47.6-compliant shape."""
    p = _yaml_path(mode_id)
    assert p.exists(), f"Missing registry YAML at {p}"
    data = yaml.safe_load(p.read_text())
    for field in REQUIRED_FIELDS:
        assert field in data, f"{mode_id}: missing field '{field}'"
    assert data["id"] == mode_id
    assert data["type"] == "conversation_mode"
    assert data["status"] in ("real", "planned", "deprecated")
    assert isinstance(data["shipped"], int)
    assert isinstance(data["allowed_tools"], list)


def test_conversation_mode_passes_8_stage_validator():
    """All 6 conversation_mode YAMLs pass the 8-stage capability registry validator."""
    from core.registry.capability_registry import CapabilityRegistry  # type: ignore[import-not-found]

    # Reset singleton if a prior test initialised it.
    CapabilityRegistry._instance = None
    try:
        reg = CapabilityRegistry.initialize(_VM107_ROOT / "registry")
        ids = {e.id for e in reg.snapshot.entries}
        for mode_id in EXPECTED_MODES:
            assert mode_id in ids, f"Validator did not surface mode id {mode_id}"
    finally:
        CapabilityRegistry._instance = None


def test_host_agent_profiles_resolve():
    """Every conversation_mode host_agent_profile must reference a registered agent_profile."""
    profile_dir = _VM107_ROOT / "registry" / "agent_profile"
    profile_ids = set()
    for f in profile_dir.glob("*.yaml"):
        d = yaml.safe_load(f.read_text())
        if isinstance(d, dict) and d.get("id"):
            profile_ids.add(d["id"])

    for mode in EXPECTED_MODES:
        data = yaml.safe_load(_yaml_path(mode).read_text())
        host = data["host_agent_profile"]
        base = str(host).split(".")[0]
        assert base in profile_ids, (
            f"conversation_mode {mode!r} host_agent_profile={host!r} "
            f"but no agent_profile with that id is registered."
        )


def test_skill_addendum_resolves_when_set():
    """Conversation modes that declare skill_addendum must reference a registered skill id."""
    skill_dir = _VM107_ROOT / "registry" / "skill"
    skill_ids = set()
    for f in skill_dir.glob("*.yaml"):
        d = yaml.safe_load(f.read_text())
        if isinstance(d, dict) and d.get("id"):
            skill_ids.add(d["id"])

    for mode in EXPECTED_MODES:
        data = yaml.safe_load(_yaml_path(mode).read_text())
        addendum = data.get("skill_addendum")
        if addendum is None:
            continue
        assert addendum in skill_ids, (
            f"conversation_mode {mode!r} skill_addendum={addendum!r} "
            f"but no skill with that id is registered."
        )
