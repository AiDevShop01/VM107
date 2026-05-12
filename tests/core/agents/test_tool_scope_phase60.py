"""Phase 60 sub-profile tool scope enforcement tests — CTX-§2 + CTX-§5.

Tests the HARD_ALLOWED_TOOLS + SENSITIVE_TOOLS + PROFILE_TO_AGENT_ID extensions
to tool_scope.py for the 12 new Phase 60 (dotted agent_id) profile entries.

Key contracts tested:
  - persist_narrative is in SENSITIVE_TOOLS
  - Only _writer sub-profiles have persist_narrative in HARD_ALLOWED_TOOLS
  - _reader and _analyzer profiles cannot call persist_narrative → UnauthorizedToolError
  - _writer cannot call read-tier tools (via agent.yaml denied_tools mechanism; xfail until 60-09)
  - All 12 dotted agent_ids appear in HARD_ALLOWED_TOOLS and PROFILE_TO_AGENT_ID
  - Existing profiles (agent_zero, idea_agent, strategy_agent) remain unchanged

NOTE on dotted agent_ids:
  Keys in HARD_ALLOWED_TOOLS are DOTTED AGENT_ID STRINGS (runtime routing), NOT filesystem paths.
  On-disk layout per CONTEXT.md §2 is NESTED: agents/<profile>/_writer/agent.yaml
  60-01 Task 1b handles the dotted-id → nested-path mapping at discovery time.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tool_scope():
    """Import core.agents.tool_scope once for the module."""
    from core.agents import tool_scope as ts
    return ts


@pytest.fixture(scope="module")
def fixtures_dir():
    """Return path to the local fixtures/ dir (stub agent.yaml files)."""
    return Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Tests — SENSITIVE_TOOLS
# ---------------------------------------------------------------------------

def test_persist_narrative_is_sensitive(tool_scope):
    """persist_narrative must be in SENSITIVE_TOOLS (Phase 60 writer-tier tool)."""
    assert "persist_narrative" in tool_scope.SENSITIVE_TOOLS, (
        "persist_narrative must be a HARD-scoped (SENSITIVE) tool. "
        "Only _writer sub-profiles have it in HARD_ALLOWED_TOOLS."
    )


# ---------------------------------------------------------------------------
# Tests — HARD_ALLOWED_TOOLS entries for Phase 60 (12 new entries)
# ---------------------------------------------------------------------------

PHASE_60_TOP_LEVEL_PROFILES = [
    "trade_auditor_agent",
    "behavioral_mentor_agent",
    "weekly_review_agent",
]

PHASE_60_WRITER_PROFILES = [
    "trade_auditor_agent._writer",
    "behavioral_mentor_agent._writer",
    "weekly_review_agent._writer",
]

PHASE_60_NON_WRITER_PROFILES = [
    "trade_auditor_agent._reader",
    "trade_auditor_agent._analyzer",
    "behavioral_mentor_agent._reader",
    "behavioral_mentor_agent._analyzer",
    "weekly_review_agent._reader",
    "weekly_review_agent._analyzer",
]

ALL_PHASE_60_PROFILES = (
    PHASE_60_TOP_LEVEL_PROFILES
    + PHASE_60_WRITER_PROFILES
    + PHASE_60_NON_WRITER_PROFILES
)


@pytest.mark.parametrize("profile", ALL_PHASE_60_PROFILES)
def test_all_phase60_profiles_in_hard_allowed_tools(tool_scope, profile):
    """All 12 Phase 60 dotted agent_ids must appear in HARD_ALLOWED_TOOLS."""
    assert profile in tool_scope.HARD_ALLOWED_TOOLS, (
        f"'{profile}' not found in HARD_ALLOWED_TOOLS. "
        f"All 12 Phase 60 profiles (3 top-level + 9 sub-profiles) must be registered."
    )


@pytest.mark.parametrize("profile", ALL_PHASE_60_PROFILES)
def test_all_phase60_profiles_in_profile_to_agent_id(tool_scope, profile):
    """All 12 Phase 60 dotted agent_ids must appear in PROFILE_TO_AGENT_ID."""
    assert profile in tool_scope.PROFILE_TO_AGENT_ID, (
        f"'{profile}' not found in PROFILE_TO_AGENT_ID. "
        f"The dotted profile name is its own agent_id for Phase 60 sub-profiles."
    )


# ---------------------------------------------------------------------------
# Tests — writer sub-profiles ALLOWED to call persist_narrative
# ---------------------------------------------------------------------------

def test_writer_profile_allows_persist_narrative(tool_scope):
    """check_tool_scope for a _writer profile + persist_narrative must not raise."""
    # Should not raise
    tool_scope.check_tool_scope("trade_auditor_agent._writer", "persist_narrative")


@pytest.mark.parametrize("writer_profile", PHASE_60_WRITER_PROFILES)
def test_all_writers_allow_persist_narrative(tool_scope, writer_profile):
    """All 3 _writer sub-profiles across the 3 Phase 60 agents allow persist_narrative."""
    tool_scope.check_tool_scope(writer_profile, "persist_narrative")


# ---------------------------------------------------------------------------
# Tests — non-writer profiles DENIED persist_narrative → UnauthorizedToolError
# ---------------------------------------------------------------------------

def test_analyzer_denied_persist(tool_scope):
    """CTX-§2 — trade_auditor_agent._analyzer cannot call persist_narrative."""
    from core.agents.tool_scope import UnauthorizedToolError
    with pytest.raises(UnauthorizedToolError):
        tool_scope.check_tool_scope("trade_auditor_agent._analyzer", "persist_narrative")


def test_reader_denied_persist(tool_scope):
    """trade_auditor_agent._reader cannot call persist_narrative."""
    from core.agents.tool_scope import UnauthorizedToolError
    with pytest.raises(UnauthorizedToolError):
        tool_scope.check_tool_scope("trade_auditor_agent._reader", "persist_narrative")


def test_top_level_profile_denied_persist(tool_scope):
    """The top-level trade_auditor_agent profile cannot call persist_narrative."""
    from core.agents.tool_scope import UnauthorizedToolError
    with pytest.raises(UnauthorizedToolError):
        tool_scope.check_tool_scope("trade_auditor_agent", "persist_narrative")


@pytest.mark.parametrize("non_writer_profile", PHASE_60_NON_WRITER_PROFILES + PHASE_60_TOP_LEVEL_PROFILES)
def test_non_writer_profiles_denied_persist_narrative(tool_scope, non_writer_profile):
    """All non-writer Phase 60 profiles (readers, analyzers, top-level) cannot persist_narrative."""
    from core.agents.tool_scope import UnauthorizedToolError
    with pytest.raises(UnauthorizedToolError):
        tool_scope.check_tool_scope(non_writer_profile, "persist_narrative")


# ---------------------------------------------------------------------------
# Tests — _writer profile DENIED read tools (via agent.yaml denied_tools)
# 60-09 landed: live NESTED agent.yaml exists — test loads it directly
# ---------------------------------------------------------------------------


def test_writer_denied_read_tools(tool_scope):
    """CTX-§2 — _writer sub-profile agent.yaml denies all read-tier tools.

    Verifies the live NESTED agent.yaml (agents/trade_auditor_agent/_writer/agent.yaml)
    contains `denied_tools` that includes all read-tier tools. Enforced at runtime via
    the per-profile `denied_tools` list in agent.yaml (separate from SENSITIVE_TOOLS).

    60-09 created the actual NESTED agent.yaml — this replaces the xfail sentinel
    that was seeded in Plan 60-05.
    """
    import os
    import yaml

    _root = Path(__file__).resolve().parent.parent.parent.parent
    writer_yaml = _root / "agents" / "trade_auditor_agent" / "_writer" / "agent.yaml"
    assert writer_yaml.exists(), (
        f"NESTED _writer/agent.yaml missing at {writer_yaml}. "
        "Plan 60-09 should have created this file."
    )

    with open(writer_yaml) as f:
        agent_data = yaml.safe_load(f)

    denied = agent_data.get("denied_tools", [])

    # All read-tier tools must be denied
    read_tier_tools = [
        "lookup_replay_artifact",
        "fetch_replay_frame",
        "get_trade_context",
    ]
    for tool in read_tier_tools:
        assert tool in denied, (
            f"_writer/agent.yaml must deny read-tier tool '{tool}' "
            f"(CTX-§2 — writer tier cannot call read tools). "
            f"Current denied_tools: {denied}"
        )

    # persist_narrative must be in allowed_tools (writer-tier ONLY)
    allowed = agent_data.get("allowed_tools", [])
    assert "persist_narrative" in allowed, (
        "_writer/agent.yaml must have persist_narrative in allowed_tools"
    )


# ---------------------------------------------------------------------------
# Tests — existing profiles unchanged (regression guard)
# ---------------------------------------------------------------------------

def test_existing_profiles_unaffected(tool_scope):
    """Existing profiles (agent_zero, idea_agent, strategy_agent) remain in HARD_ALLOWED_TOOLS."""
    assert "agent_zero" in tool_scope.HARD_ALLOWED_TOOLS
    assert "idea_agent" in tool_scope.HARD_ALLOWED_TOOLS
    assert "strategy_agent" in tool_scope.HARD_ALLOWED_TOOLS


def test_existing_profile_to_agent_id_unaffected(tool_scope):
    """Existing PROFILE_TO_AGENT_ID entries are not modified."""
    assert tool_scope.PROFILE_TO_AGENT_ID["agent0"] == "agent_zero"
    assert tool_scope.PROFILE_TO_AGENT_ID["idea_agent"] == "idea_agent"
    assert tool_scope.PROFILE_TO_AGENT_ID["strategy_agent"] == "strategy_agent"
    assert tool_scope.PROFILE_TO_AGENT_ID["default"] == "default"
