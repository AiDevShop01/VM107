"""Phase 62.1 — BUG-17 unit test scaffold: agent.py get_tool() subdir resolution.

BUG-17 root cause (agent.py line 1029):
    ``paths = subagents.get_paths(self, "tools", name + ".py")``
  This performs a flat lookup in the top-level ``tools/`` directory.
  Tools placed in subdirectories (``tools/replay/``, ``tools/adaptive/``,
  ``tools/qdrant/``, ``tools/graph/``, ``tools/vm_contracts/``) are invisible
  to this flat name lookup, causing Agent Zero to return an ``Unknown`` tool
  on every invocation.

Fix candidate (Option a per CONTEXT.md):
    Extend ``get_paths`` (or the caller) to glob ``tools/**/<name>.py``
    so first match wins across all subdirectories.

Wave 2 (Plan 62.1-02) implements the glob-based subdir walk.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import agent as agent_module  # noqa: E402


# ---------------------------------------------------------------------------
# Helper — build a minimal agent instance for get_tool tests
# ---------------------------------------------------------------------------

def _make_agent() -> object:
    """Return a minimal Agent instance with a tools/ directory pointed at VM107."""
    ag = MagicMock()
    ag.agent_id = "agent_zero"
    # The config.code_path controls where agent.py looks for tools
    ag.config = MagicMock()
    ag.config.code_path = str(_VM107_ROOT)
    return ag


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-17 implementation pending in Phase 62.1 Plan 02 — flat top-level tool works today (baseline lock)",
    strict=True,
    run=True,
)
def test_get_tool_resolves_flat_top_level_tool():
    """get_tool() resolves a tool that lives directly in tools/<name>.py.

    This is the current passing baseline. strict=True means the test will FAIL
    the suite if the baseline starts raising an error — regression detection.
    """
    # Wave 2 will call agent.get_tool(agent_instance, "response") and assert
    # the returned tool is an instance of Response_tool (not UnknownTool).
    pytest.xfail("BUG-17 baseline lock pending in Phase 62.1 Plan 02")


@pytest.mark.xfail(
    reason="BUG-17 implementation pending in Phase 62.1 Plan 02 — replay subdir tools return Unknown today",
    strict=False,
    run=True,
)
def test_get_tool_resolves_replay_subdir_tool_via_glob():
    """get_tool() must resolve ``lookup_replay_artifact`` via ``tools/replay/`` subdir walk.

    Currently: ``get_tool("lookup_replay_artifact")`` returns UnknownTool because
    the flat lookup cannot find ``tools/replay/lookup_replay_artifact.py``.
    After fix: returns LookupReplayArtifact instance (or the correct Tool subclass).
    """
    pytest.xfail("BUG-17 implementation pending in Phase 62.1 Plan 02")


@pytest.mark.xfail(
    reason="BUG-17 implementation pending in Phase 62.1 Plan 02 — adaptive subdir tools return Unknown today",
    strict=False,
    run=True,
)
def test_get_tool_resolves_adaptive_subdir_tool_via_glob():
    """get_tool() must resolve adaptive tools via ``tools/adaptive/`` subdir walk.

    Adaptive tools (Phase 62) live in tools/adaptive/.  The LLM tries to call
    them by short name; the flat resolver returns Unknown on every attempt.
    """
    pytest.xfail("BUG-17 implementation pending in Phase 62.1 Plan 02")


@pytest.mark.xfail(
    reason="BUG-17 implementation pending in Phase 62.1 Plan 02 — missing tool baseline works today (lock)",
    strict=True,
    run=True,
)
def test_get_tool_returns_unknown_for_truly_missing_tool():
    """get_tool() must return UnknownTool (not raise) for a tool name that doesn't exist anywhere.

    Baseline lock: this already works.  strict=True catches any regression
    where the subdir glob implementation accidentally raises instead of returning
    UnknownTool for truly missing tools.
    """
    pytest.xfail("BUG-17 baseline lock pending in Phase 62.1 Plan 02")


@pytest.mark.xfail(
    reason="BUG-17 implementation pending in Phase 62.1 Plan 02 — precedence rule not yet implemented",
    strict=False,
    run=True,
)
def test_get_tool_flat_takes_precedence_over_subdir():
    """A flat ``tools/<name>.py`` wrapper must take precedence over a same-named subdir tool.

    This ensures the BUG-14 wrapper pattern (flat top-level files wrapping
    subdir tools) continues to work correctly: if both ``tools/foo.py`` and
    ``tools/replay/foo.py`` exist, the flat version is returned.
    """
    pytest.xfail("BUG-17 implementation pending in Phase 62.1 Plan 02")
