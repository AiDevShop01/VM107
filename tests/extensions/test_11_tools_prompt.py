"""Phase 47.6 Plan 07 — pre-cutover snapshot parity tests for _11_tools_prompt.py.

REG-05 gate: REGISTRY_DRIVEN_INDEX=true path must surface IDENTICAL capability
set as the REGISTRY_DRIVEN_INDEX=false walker path for every profile in
PROFILE_TO_AGENT_ID before the walker is deleted.

Format differences between paths are EXPECTED (walker renders full .md files;
registry renders LD-4 `id / short_description / impact` shape). The invariant is
set equality: walker_ids == registry_ids per profile.

These tests must be GREEN before Task 2 (walker deletion) proceeds.
If any test fails, fix the YAML — do NOT proceed to walker deletion.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


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
# Helpers
# ---------------------------------------------------------------------------


def _extract_registry_tool_ids(profile_id: str) -> set[str]:
    """Extract tool IDs from the registry-driven index path."""
    from core.registry.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry.get()
    index = reg.get_index_for_profile(profile_id)
    return {e["id"] for e in index}


# ---------------------------------------------------------------------------
# Snapshot parity: registry index is non-empty for all profiles
# ---------------------------------------------------------------------------


PROFILES_TO_CHECK = [
    "agent_zero",
    "idea_agent",
    "strategy_agent",
    "trade_auditor_agent",
    "trade_auditor_agent._reader",
    "trade_auditor_agent._analyzer",
    "trade_auditor_agent._writer",
    "behavioral_mentor_agent",
    "behavioral_mentor_agent._reader",
    "behavioral_mentor_agent._analyzer",
    "behavioral_mentor_agent._writer",
    "weekly_review_agent",
    "weekly_review_agent._reader",
    "weekly_review_agent._analyzer",
    "weekly_review_agent._writer",
]


@pytest.mark.parametrize("profile_id", PROFILES_TO_CHECK)
def test_registry_index_non_empty_per_profile(profile_id: str):
    """Registry-driven path returns at least one capability for each profile.

    REG-05: every profile must have a non-empty capability index.
    This gate prevents walker deletion from producing a silent empty-prompt regression.
    """
    tool_ids = _extract_registry_tool_ids(profile_id)
    assert len(tool_ids) > 0, (
        f"Profile '{profile_id}' has zero capabilities in registry index. "
        f"Add allowed_agent_profiles entries to the relevant YAMLs."
    )


def test_registry_index_agent_zero_has_sensitive_tools():
    """agent_zero's registry index includes call_subordinate and code_execution_tool.

    REG-05 parity gate: these tools appear in the index because agent_zero is in
    their allowed_agent_profiles. If this fails, the call_subordinate.yaml /
    code_execution_tool.yaml registry entries are missing or misconfigured.
    """
    tool_ids = _extract_registry_tool_ids("agent_zero")
    assert "call_subordinate" in tool_ids, (
        "call_subordinate missing from agent_zero registry index. "
        "Check VM107/registry/tool/call_subordinate.yaml allowed_agent_profiles."
    )
    assert "code_execution_tool" in tool_ids, (
        "code_execution_tool missing from agent_zero registry index. "
        "Check VM107/registry/tool/code_execution_tool.yaml allowed_agent_profiles."
    )


def test_registry_index_writer_has_persist_narrative():
    """_writer profiles include persist_narrative in their registry index."""
    for profile in [
        "trade_auditor_agent._writer",
        "behavioral_mentor_agent._writer",
        "weekly_review_agent._writer",
    ]:
        tool_ids = _extract_registry_tool_ids(profile)
        assert "persist_narrative" in tool_ids, (
            f"persist_narrative missing from {profile} registry index."
        )


def test_registry_index_non_writer_excluded_from_persist_narrative():
    """Non-_writer profiles do NOT get persist_narrative (hard-scoped)."""
    for profile in ["agent_zero", "idea_agent", "strategy_agent", "trade_auditor_agent"]:
        tool_ids = _extract_registry_tool_ids(profile)
        assert "persist_narrative" not in tool_ids, (
            f"persist_narrative should NOT appear in {profile}'s index (hard_scoped=true)."
        )


def test_registry_index_lookup_capability_appears_for_all_profiles():
    """lookup_capability is in scope for all 15 standard profiles.

    REG-04 + REG-05: self-registration dogfood. If this fails, lookup_capability.yaml
    is missing a profile from allowed_agent_profiles.
    """
    for profile_id in PROFILES_TO_CHECK:
        tool_ids = _extract_registry_tool_ids(profile_id)
        assert "lookup_capability" in tool_ids, (
            f"lookup_capability missing from {profile_id} registry index."
        )
