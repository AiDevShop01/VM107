"""Phase 47.6 Plan 07 — pre-cutover parity tests for tool_scope.py.

REG-05 gate: old is_tool_allowed() (dict-based HARD_ALLOWED_TOOLS) must return
IDENTICAL results to new CapabilityRegistry.is_capability_in_scope() for every
(profile, sensitive_tool) pair BEFORE the walker is deleted and BEFORE tool_scope.py
is refactored to the populated-projection pattern.

Parity is checked only for SENSITIVE_TOOLS (the HARD-scoped tools) because:
- Soft tools (not in SENSITIVE_TOOLS) always return True in old code.
- The registry may not enumerate all soft tools; that's intentional.
- The security boundary we're protecting is: who can call SENSITIVE tools.

These tests must be GREEN before Task 2 (tool_scope refactor) proceeds.
If any test fails, the registry YAML for that tool has a missing/incorrect
allowed_agent_profiles entry.

Snapshot of pre-refactor constants (hermetic — won't change after Task 2):
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Snapshot of pre-refactor tool_scope constants
# (captured here so the tests are hermetic after Task 2 refactors the module)
# ---------------------------------------------------------------------------

# These are the profile names as they appear in PROFILE_TO_AGENT_ID keys.
# Profile "agent0" maps to agent_id "agent_zero" in the old code.
_OLD_HARD_ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    "agent_zero": frozenset({"call_subordinate", "code_execution_tool"}),
    "idea_agent": frozenset(),
    "strategy_agent": frozenset(),
    "trade_auditor_agent": frozenset(),
    "trade_auditor_agent._reader": frozenset(),
    "trade_auditor_agent._analyzer": frozenset(),
    "trade_auditor_agent._writer": frozenset({"persist_narrative"}),
    "behavioral_mentor_agent": frozenset(),
    "behavioral_mentor_agent._reader": frozenset(),
    "behavioral_mentor_agent._analyzer": frozenset(),
    "behavioral_mentor_agent._writer": frozenset({"persist_narrative"}),
    "weekly_review_agent": frozenset(),
    "weekly_review_agent._reader": frozenset(),
    "weekly_review_agent._analyzer": frozenset(),
    "weekly_review_agent._writer": frozenset({"persist_narrative"}),
}

_OLD_SENSITIVE_TOOLS: frozenset[str] = frozenset({
    "call_subordinate",
    "code_execution_tool",
    "persist_narrative",
})

# Profile-to-agent_id mapping: the old code distinguishes "agent0" (profile name)
# from "agent_zero" (agent_id). The registry uses "agent_zero" directly.
# test_parity uses agent_ids (keys of HARD_ALLOWED_TOOLS), not profile names.
_AGENT_IDS = list(_OLD_HARD_ALLOWED_TOOLS.keys())
_SENSITIVE_TOOLS = list(_OLD_SENSITIVE_TOOLS)


def _old_is_tool_allowed(agent_id: str, tool_name: str) -> bool:
    """Snapshot of the pre-refactor is_tool_allowed() logic."""
    if tool_name not in _OLD_SENSITIVE_TOOLS:
        return True  # soft-scoped — always allowed
    return tool_name in _OLD_HARD_ALLOWED_TOOLS.get(agent_id, frozenset())


# ---------------------------------------------------------------------------
# Registry fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def registry_initialized():
    """Ensure CapabilityRegistry is initialized with the real registry for all tests."""
    from core.registry.capability_registry import CapabilityRegistry

    original_instance = CapabilityRegistry._instance
    if CapabilityRegistry._instance is None:
        CapabilityRegistry.initialize(_VM107_ROOT / "registry")
    yield
    CapabilityRegistry._instance = original_instance


# ---------------------------------------------------------------------------
# Parity tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_id", _AGENT_IDS)
@pytest.mark.parametrize("tool_name", _SENSITIVE_TOOLS)
def test_sensitive_tool_parity(agent_id: str, tool_name: str):
    """old is_tool_allowed() == new is_capability_in_scope() for all SENSITIVE_TOOLS.

    REG-05: This is the hard gate before walker deletion. Any mismatch means
    a YAML registry entry has wrong allowed_agent_profiles. Fix the YAML.

    Note: Only SENSITIVE_TOOLS are checked (HARD-scoped security boundary).
    Soft tools (not in SENSITIVE_TOOLS) always return True in both old and
    new code (old: explicit True; new: lookup_capability et al. appear in
    the registry for all profiles).
    """
    from core.registry.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry.get()
    old_result = _old_is_tool_allowed(agent_id, tool_name)
    new_result = reg.is_capability_in_scope(profile=agent_id, capability_id=tool_name)

    assert old_result == new_result, (
        f"Parity mismatch for (agent_id={agent_id!r}, tool={tool_name!r}): "
        f"old_is_tool_allowed={old_result}, "
        f"new_is_capability_in_scope={new_result}. "
        f"Fix: update allowed_agent_profiles in "
        f"VM107/registry/tool/{tool_name}.yaml (Pitfall 6)."
    )


def test_is_tool_allowed_imports_from_tool_scope():
    """Confirm is_tool_allowed is importable from core.agents.tool_scope.

    Guards against import errors introduced by the Task 2 refactor.
    """
    from core.agents.tool_scope import is_tool_allowed

    # Basic smoke test: soft tool always returns True
    assert is_tool_allowed("any_agent", "search_knowledge") is True


def test_profile_to_agent_id_key_agent0():
    """PROFILE_TO_AGENT_ID['agent0'] == 'agent_zero' — filesystem bridge preserved."""
    from core.agents.tool_scope import PROFILE_TO_AGENT_ID

    assert PROFILE_TO_AGENT_ID.get("agent0") == "agent_zero"
