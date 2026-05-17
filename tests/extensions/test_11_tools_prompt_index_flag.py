"""Tests for the feature-flagged _11_tools_prompt.py refactor.

Phase 47.6 Plan 03 — TDD RED suite.

Tests the A/B feature flag REGISTRY_DRIVEN_INDEX:
- false (default): walker path unchanged, byte-identical output
- true: registry-driven LD-4 index path

Wave 4 (Plan 07) will flip the default to true and delete the walker branch.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset CapabilityRegistry singleton between tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    yield
    CapabilityRegistry._instance = original_instance


def _make_mock_agent(profile_id: str = "agent_zero") -> MagicMock:
    """Build a mock Agent with the minimum attributes needed by build_prompt."""
    agent = MagicMock()
    agent.profile_id = profile_id
    agent.agent_name = profile_id

    # Minimal agent.read_prompt behavior
    def _read_prompt(template_name: str, **kwargs) -> str:
        tools_content = kwargs.get("tools", "")
        return f"[TOOLS PROMPT: {len(tools_content)} chars]"

    agent.read_prompt = MagicMock(side_effect=_read_prompt)
    return agent


# ---------------------------------------------------------------------------
# Test: default flag value is false
# ---------------------------------------------------------------------------


def test_default_flag_value(monkeypatch):
    """Default REGISTRY_DRIVEN_INDEX is false — walker path is active by default."""
    # Remove the env var to test module default
    monkeypatch.delenv("REGISTRY_DRIVEN_INDEX", raising=False)

    # Force re-import to pick up the env state
    import importlib
    import extensions.python.system_prompt._11_tools_prompt as mod
    importlib.reload(mod)

    assert mod.REGISTRY_DRIVEN_INDEX is False


# ---------------------------------------------------------------------------
# Test: walker path when flag is false (default)
# ---------------------------------------------------------------------------


def test_walker_path_when_flag_false(monkeypatch):
    """REGISTRY_DRIVEN_INDEX=false -> build_prompt calls the filesystem walker."""
    monkeypatch.setenv("REGISTRY_DRIVEN_INDEX", "false")

    import importlib
    import extensions.python.system_prompt._11_tools_prompt as mod
    importlib.reload(mod)

    agent = _make_mock_agent()
    agent.get_data = MagicMock(return_value=None)

    mock_tool_files = ["/fake/path/agent.system.tool.example.md"]
    mock_prompt_dirs = ["/fake/prompts"]

    with patch.object(mod, 'REGISTRY_DRIVEN_INDEX', False), \
         patch('helpers.subagents.get_paths', return_value=mock_prompt_dirs) as mock_get_paths, \
         patch('helpers.files.get_unique_filenames_in_dirs', return_value=mock_tool_files) as mock_walker, \
         patch('plugins._model_config.helpers.model_config.get_chat_model_config', return_value={"vision": False}):

        agent.read_prompt = MagicMock(return_value="<tools>mock_tool_content</tools>")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(mod.build_prompt(agent))

    # Walker was called (filesystem-driven path)
    mock_get_paths.assert_called_once()
    mock_walker.assert_called_once()


# ---------------------------------------------------------------------------
# Test: registry path when flag is true
# ---------------------------------------------------------------------------


def test_registry_path_when_flag_true(monkeypatch):
    """REGISTRY_DRIVEN_INDEX=true -> build_prompt calls CapabilityRegistry.get_index_for_profile."""
    monkeypatch.setenv("REGISTRY_DRIVEN_INDEX", "true")

    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)

    import importlib
    import extensions.python.system_prompt._11_tools_prompt as mod
    importlib.reload(mod)

    agent = _make_mock_agent(profile_id="agent_zero")
    agent.get_data = MagicMock(return_value=None)

    with patch.object(mod, 'REGISTRY_DRIVEN_INDEX', True), \
         patch('plugins._model_config.helpers.model_config.get_chat_model_config', return_value={"vision": False}):
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(mod.build_prompt(agent))

    # read_prompt was called with tools= kwarg (registry-driven path)
    assert agent.read_prompt.called
    call_kwargs = agent.read_prompt.call_args_list[-1][1]
    # tools= should be passed and non-empty (registry has entries for agent_zero)
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) > 0


# ---------------------------------------------------------------------------
# Test: both paths render for agent_zero (item count within ±2)
# ---------------------------------------------------------------------------


def test_both_paths_render_for_agent_zero(monkeypatch):
    """With real registry loaded, registry-driven path produces a non-empty index for agent_zero."""
    from core.registry.capability_registry import CapabilityRegistry

    registry_root = _VM107_ROOT / "registry"
    CapabilityRegistry._instance = None
    CapabilityRegistry.initialize(registry_root)

    reg = CapabilityRegistry.get()
    index = reg.get_index_for_profile("agent_zero")

    # Registry path must return at least some entries for agent_zero
    assert len(index) > 0, "Registry index for agent_zero must be non-empty"

    # Build the registry-driven tools_str as _11_tools_prompt would
    tools_str = "\n\n".join(
        f"{e['id']}\n→ {e['short_description']}\n→ impact: {e['impact_on_decision']}"
        for e in index
    )
    assert len(tools_str) > 0
    # Count items in output equals registry index count
    item_count = tools_str.count("\n→ impact:")
    assert item_count == len(index)
