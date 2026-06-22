"""Phase 89.1 Plan 03 — Tool-scope filter tests.

Two sections:
  Helper-level (Tests 1-9):  apply_tool_scope() pure-function contract.
  Integration (Tests 10-12): _05_tool_scope_filter.py system_prompt extension.

Dispatch-path validation summary (Task 3):
  - CapabilityRegistry.get() is patched via unittest.mock.patch at the
    extension module import site (not at test-module level) to avoid
    bootstrapping the real registry in CI.
  - The extension is called directly with agent stubs matching the
    production Agent contract (single-arg get_data, two-arg set_data).
  - Tests 10-11 verify the no-op paths (legacy string profile, bare dict).
  - Test 12 verifies the full macro_investigator filter produces exactly
    the 4 expected tool IDs and NONE of the 3 A0 defaults.

REQ-89-9.3 — tool-scope filter:
  - allowed_tools restricts the active registry to EXACTLY those tools.
  - denied_tools strips named tools from whatever list the agent would otherwise use.
  - Both set: first restrict to allowed, then strip denied (deny wins on collision).
  - No allowed_tools / denied_tools: tool registry UNCHANGED.
  - Tools listed but not in available: silently skipped (no KeyError).
  - Type-preserving: list[str]→list[str], dict→dict, list[dict-with-"id"]→list[dict].
"""
from __future__ import annotations

import sys
import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VM107_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from tests.phase89_1.fixtures.profile_yaml_samples import (
    AVAILABLE_TOOLS_DICT,
    AVAILABLE_TOOLS_INDEX_ENTRIES,
    AVAILABLE_TOOLS_LIST,
    PROFILE_BARE_DICT,
    PROFILE_LEGACY_STRING,
    PROFILE_MACRO_INVESTIGATOR_DICT,
)

# ---------------------------------------------------------------------------
# Helper import — will fail (RED) until helpers/tool_scope.py is created
# ---------------------------------------------------------------------------

from helpers.tool_scope import apply_tool_scope  # noqa: E402  (after path setup)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def _tool_names_from_index(entries: list[dict]) -> list[str]:
    return [e["id"] for e in entries]


# ===========================================================================
# Helper-level tests (Tests 1-9) — apply_tool_scope pure function
# ===========================================================================


@pytest.mark.phase89_1
class TestApplyToolScope:

    # ----- Test 1 -----------------------------------------------------------

    def test_no_allowed_no_denied_passes_through(self):
        """allowed=None, denied=None → return available_tools UNCHANGED."""
        result = apply_tool_scope(AVAILABLE_TOOLS_LIST, allowed=None, denied=None)
        assert result == AVAILABLE_TOOLS_LIST

    # ----- Test 2 -----------------------------------------------------------

    def test_allowed_only_restricts_to_listed(self):
        """allowed=[...] → only tools in allowed survive."""
        allowed = ["vm102.indicator_history", "belief_store.query"]
        result = apply_tool_scope(AVAILABLE_TOOLS_LIST, allowed=allowed, denied=None)
        assert set(result) == set(allowed)

    # ----- Test 3 -----------------------------------------------------------

    def test_denied_only_strips_listed(self):
        """denied=[...] → those names are removed; the rest survive."""
        denied = ["code_execution_tool", "text_editor"]
        result = apply_tool_scope(AVAILABLE_TOOLS_LIST, allowed=None, denied=denied)
        for name in denied:
            assert name not in result
        # Everything else should still be present
        expected_remaining = [t for t in AVAILABLE_TOOLS_LIST if t not in denied]
        assert set(result) == set(expected_remaining)

    # ----- Test 4 -----------------------------------------------------------

    def test_both_set_deny_wins_on_collision(self):
        """allowed has 'X', denied has 'X' → 'X' NOT in result (deny wins)."""
        tool_x = "vm102.indicator_history"
        allowed = [tool_x, "belief_store.query"]
        denied = [tool_x]  # collides with allowed
        result = apply_tool_scope(AVAILABLE_TOOLS_LIST, allowed=allowed, denied=denied)
        assert tool_x not in result
        assert "belief_store.query" in result

    # ----- Test 5 -----------------------------------------------------------

    def test_allowed_with_missing_tool_silently_skipped(self):
        """Tool in allowed but absent from available → silently skipped, no KeyError."""
        allowed = ["vm102.indicator_history", "search_macro_research"]  # Phase 92 absent
        result = apply_tool_scope(AVAILABLE_TOOLS_LIST, allowed=allowed, denied=None)
        # search_macro_research NOT in AVAILABLE_TOOLS_LIST → must not raise
        assert "search_macro_research" not in result
        assert "vm102.indicator_history" in result

    # ----- Test 6 -----------------------------------------------------------

    def test_dict_input_returns_dict(self):
        """dict input → dict output (type preservation)."""
        allowed = ["vm102.indicator_history", "belief_store.query"]
        result = apply_tool_scope(AVAILABLE_TOOLS_DICT, allowed=allowed, denied=None)
        assert isinstance(result, dict)
        assert set(result.keys()) == set(allowed)

    # ----- Test 7 -----------------------------------------------------------

    def test_list_input_returns_list(self):
        """list[str] input → list[str] output (type preservation)."""
        result = apply_tool_scope(AVAILABLE_TOOLS_LIST, allowed=None, denied=None)
        assert isinstance(result, list)
        assert all(isinstance(t, str) for t in result)

    # ----- Test 8 -----------------------------------------------------------

    def test_index_entries_input_returns_index_entries(self):
        """list[dict] (CapabilityRegistry index) input → list[dict] output matched by 'id'."""
        allowed = ["vm102.indicator_history", "vm105.neo4j_macro_graph_walker"]
        result = apply_tool_scope(
            AVAILABLE_TOOLS_INDEX_ENTRIES, allowed=allowed, denied=None
        )
        assert isinstance(result, list)
        assert all(isinstance(e, dict) for e in result)
        ids = _tool_names_from_index(result)
        assert set(ids) == set(allowed)

    # ----- Test 9 -----------------------------------------------------------

    def test_macro_investigator_scope_produces_expected_4_tools(self):
        """End-to-end fixture run: macro_investigator allowed/denied applied to 7-tool index.

        Expected result: exactly {vm102.indicator_history, vm105.neo4j_macro_graph_walker,
        episodic_memory_service.query, belief_store.query} — NOT the 3 A0 defaults.
        search_macro_research is in allowed but absent from available → silently skipped.
        """
        profile = PROFILE_MACRO_INVESTIGATOR_DICT
        allowed = profile["allowed_tools"]
        denied = profile["denied_tools"]

        result = apply_tool_scope(
            AVAILABLE_TOOLS_INDEX_ENTRIES, allowed=allowed, denied=denied
        )
        ids = set(_tool_names_from_index(result))

        expected = {
            "vm102.indicator_history",
            "vm105.neo4j_macro_graph_walker",
            "episodic_memory_service.query",
            "belief_store.query",
        }
        a0_defaults = {"code_execution_tool", "text_editor", "search_knowledge"}

        assert ids == expected, f"Expected {expected}, got {ids}"
        assert ids.isdisjoint(a0_defaults), f"A0 defaults leaked: {ids & a0_defaults}"


# ===========================================================================
# Integration tests (Tests 10-12) — _05_tool_scope_filter extension
# ===========================================================================


def _make_agent_stub(profile: Any, profile_id: str = "vm107.macro_investigator"):
    """Build a minimal agent stub that mirrors the production Agent contract."""

    class _AgentContextStub:
        class log:
            @staticmethod
            def log(**kwargs):
                pass

    class _AgentStub:
        def __init__(self, profile_val: Any, pid: str):
            self.profile = profile_val
            self.profile_id = pid
            self._data: dict[str, Any] = {}
            self.context = _AgentContextStub()

        def get_data(self, field: str):
            return self._data.get(field, None)

        def set_data(self, field: str, value: Any) -> None:
            self._data[field] = value

    return _AgentStub(profile, profile_id)


@pytest.mark.phase89_1
class TestToolScopeFilterExtension:

    # ----- Test 10 ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_extension_skipped_when_profile_is_string(self):
        """Legacy string profile → extension is a no-op; no stash."""
        from extensions.python.system_prompt._05_tool_scope_filter import (
            ToolScopeFilter,
        )

        agent = _make_agent_stub(PROFILE_LEGACY_STRING)
        ext = ToolScopeFilter(agent)
        await ext.execute()
        assert agent.get_data("_tool_scope_filtered_index") is None

    # ----- Test 11 ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_extension_skipped_when_no_tool_keys(self):
        """Bare dict profile (no allowed_tools / denied_tools) → no-op; no stash."""
        from extensions.python.system_prompt._05_tool_scope_filter import (
            ToolScopeFilter,
        )

        agent = _make_agent_stub(PROFILE_BARE_DICT)
        ext = ToolScopeFilter(agent)
        await ext.execute()
        assert agent.get_data("_tool_scope_filtered_index") is None

    # ----- Test 12 ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_extension_filters_macro_investigator_profile_end_to_end(self):
        """Full macro_investigator profile → stash has exactly the 4 expected tool IDs."""
        from extensions.python.system_prompt._05_tool_scope_filter import (
            ToolScopeFilter,
        )

        agent = _make_agent_stub(PROFILE_MACRO_INVESTIGATOR_DICT)

        # Patch CapabilityRegistry to avoid bootstrapping the real registry in CI
        mock_reg = MagicMock()
        mock_reg.get_index_for_profile.return_value = list(AVAILABLE_TOOLS_INDEX_ENTRIES)

        with patch(
            "extensions.python.system_prompt._05_tool_scope_filter.CapabilityRegistry"
        ) as mock_cls:
            mock_cls.get.return_value = mock_reg
            ext = ToolScopeFilter(agent)
            await ext.execute()

        filtered = agent.get_data("_tool_scope_filtered_index")
        assert filtered is not None, "_tool_scope_filtered_index not stashed"

        ids = {e["id"] for e in filtered}
        expected = {
            "vm102.indicator_history",
            "vm105.neo4j_macro_graph_walker",
            "episodic_memory_service.query",
            "belief_store.query",
        }
        a0_defaults = {"code_execution_tool", "text_editor", "search_knowledge"}

        assert ids == expected, f"Expected {expected}, got {ids}"
        assert ids.isdisjoint(a0_defaults), f"A0 defaults leaked: {ids & a0_defaults}"
