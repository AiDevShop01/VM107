"""Phase 71 Wave 0 — RED tests for `conversation_mode` registry YAMLs.

These tests INTENTIONALLY fail (xfail strict) until Plan 02 ships the 6
`conversation_mode` YAML entries under `VM107/registry/conversation_mode/`.

Expected YAML schema per RESEARCH.md Pattern 8:
- id: string (matches filename stem)
- type: "conversation_mode"
- status: real | planned | deprecated
- shipped: phase number (e.g., 71)
- host_agent_profile: agent profile id
- system_prompt_path: path under VM107/prompts/conversation_mode/
- allowed_tools: list[str] (tool capability ids)

REQ-71-7.

Conversation modes (CONTEXT.md Decision 4 hybrid 4c):
  pre_trade, macro_chat, execution_chat, reflection_chat, research_chat, strategy_chat
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

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


@pytest.mark.xfail(reason="Plan 02 RED — conversation_mode YAMLs not yet authored", strict=True)
def test_all_6_conversation_modes_exist():
    """Each of the 6 conversation modes must have a YAML file on disk."""
    d = _conversation_mode_dir()
    assert d.exists(), f"Plan 02 must create directory {d}"
    files = sorted(p.stem for p in d.glob("*.yaml"))
    for mode in EXPECTED_MODES:
        assert mode in files, f"Missing YAML for conversation mode: {mode}"


@pytest.mark.xfail(reason="Plan 02 RED — YAML schema pending", strict=True)
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


@pytest.mark.xfail(reason="Plan 02 RED — registry validator integration pending", strict=True)
def test_conversation_mode_passes_8_stage_validator():
    """All 6 conversation_mode YAMLs pass the 8-stage capability registry validator."""
    from core.registry.capability_registry import CapabilityRegistry  # type: ignore[import-not-found]

    reg = CapabilityRegistry.initialize(_VM107_ROOT / "registry")
    ids = {e.id for e in reg.snapshot.entries}
    for mode_id in EXPECTED_MODES:
        assert mode_id in ids, f"Validator did not surface mode id {mode_id}"
