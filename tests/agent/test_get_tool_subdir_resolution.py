"""Phase 62.1 Plan 02 — BUG-17 unit tests: agent.py get_tool() subdir resolution.

BUG-17 root cause (agent.py line 1029):
    ``paths = subagents.get_paths(self, "tools", name + ".py")``
  This performs a flat lookup in the top-level ``tools/`` directory.
  Tools placed in subdirectories (``tools/replay/``, ``tools/adaptive/``,
  ``tools/qdrant/``, ``tools/graph/``, ``tools/vm_contracts/``) are invisible
  to this flat name lookup, causing Agent Zero to return an ``Unknown`` tool
  on every invocation.

Fix (Phase 62.1 Plan 02 — Option a):
    Immediately after the flat lookup in get_tool(), if ``paths`` is empty,
    walk ``tools/**/<name>.py`` recursively using glob.glob so the first
    subdir match wins. Flat lookup still takes precedence — no behaviour
    change for the 100+ tools that already work today.

Tests (all 5 must PASS after BUG-17 fix, no xfail):
    1. test_get_tool_resolves_flat_top_level_tool          — regression lock
    2. test_get_tool_resolves_replay_subdir_tool_via_glob  — BUG-17 primary
    3. test_get_tool_resolves_adaptive_subdir_tool_via_glob — BUG-17 adaptive
    4. test_get_tool_returns_unknown_for_truly_missing_tool — Unknown baseline
    5. test_get_tool_flat_takes_precedence_over_subdir      — precedence invariant
"""
from __future__ import annotations

import glob as _glob
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ---------------------------------------------------------------------------
# Import production modules (no Agent instantiation needed — we call the
# internal logic by patching subagents.get_paths to control what the flat
# lookup returns, then verify the glob fallback fires as expected).
# ---------------------------------------------------------------------------

from helpers import extract_tools, subagents  # noqa: E402
import helpers.extension as extension  # noqa: E402

_TOOLS_ROOT = str(_VM107_ROOT / "tools")


# ---------------------------------------------------------------------------
# Helper — build a minimal Agent-like object that satisfies get_tool()'s
# internal calls to subagents.get_paths and extract_tools.load_classes_from_file.
# We do NOT instantiate the full Agent class (heavy dependencies); instead we
# call the underlying method body directly after extracting it from the class.
# ---------------------------------------------------------------------------

def _make_agent_stub() -> MagicMock:
    """Minimal stub accepted by subagents.get_paths() signature."""
    stub = MagicMock(name="AgentStub")
    stub.agent_id = "test_agent"
    stub.config = MagicMock()
    stub.config.profile = ""
    stub.context = MagicMock()
    return stub


def _call_get_tool_body(agent_stub: MagicMock, tool_name: str) -> object:
    """Execute the body of get_tool() with a given agent stub and tool name.

    This calls the *inner logic* of get_tool by invoking the raw function
    extracted from the class, bypassing the @extensible decorator so that
    extension-point scaffolding isn't needed in unit tests.

    Returns the tool class *instance* (or Unknown instance).
    """
    import agent as agent_module
    from tools.unknown import Unknown
    from helpers.tool import Tool

    # Extract the underlying function — @extensible wraps it in a wrapper;
    # access __wrapped__ (set by functools.wraps) to get the original.
    raw_fn = getattr(
        agent_module.Agent.get_tool,
        "__wrapped__",
        agent_module.Agent.get_tool,
    )
    return raw_fn(
        agent_stub,
        name=tool_name,
        method=None,
        args={},
        message="",
        loop_data=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_tool_resolves_flat_top_level_tool():
    """get_tool() resolves a tool that lives directly in tools/<name>.py.

    Regression lock — flat lookup must still work after BUG-17 patch.
    Uses ``response`` (tools/response.py) as the canonical flat tool.

    NOTE: isinstance() is not used for class identity because agent.py's
    module loader (helpers.modules.import_module) may load tools/response.py
    as module name "response" while the test imports it as "tools.response" —
    two different module objects even though they represent the same file.
    We check by class name instead, which is stable across import paths.
    """
    from tools.unknown import Unknown

    stub = _make_agent_stub()
    # The flat lookup at tools/response.py must succeed — no glob needed.
    result = _call_get_tool_body(stub, "response")
    assert not isinstance(result, Unknown), (
        "get_tool('response') should NOT return Unknown — "
        "tools/response.py exists and must resolve via flat lookup"
    )
    assert type(result).__name__ == "ResponseTool", (
        f"Expected ResponseTool, got {type(result).__name__}"
    )


def test_get_tool_resolves_graph_subdir_tool_via_glob():
    """get_tool() must resolve ``graph_search_tool`` via ``tools/graph/`` subdir walk.

    graph_search_tool has NO flat wrapper at tools/graph_search_tool.py.
    tools/graph/graph_search_tool.py contains GraphSearchTool(ContractTool).
    After BUG-17 fix, the glob fallback must find it and return GraphSearchTool.

    NOTE: Class name comparison used (not isinstance) to avoid dual-import module
    identity issues — see test_get_tool_resolves_flat_top_level_tool docstring.
    """
    from tools.unknown import Unknown

    stub = _make_agent_stub()
    result = _call_get_tool_body(stub, "graph_search_tool")
    assert not isinstance(result, Unknown), (
        "get_tool('graph_search_tool') should NOT return Unknown — "
        "tools/graph/graph_search_tool.py exists; BUG-17 glob fallback must fire"
    )
    assert type(result).__name__ == "GraphSearchTool", (
        f"Expected GraphSearchTool, got {type(result).__name__}"
    )


def test_get_tool_resolves_qdrant_subdir_tool_via_glob(caplog):
    """get_tool() must resolve ``combined_rag`` via ``tools/qdrant/`` subdir walk.

    combined_rag has NO flat wrapper at tools/combined_rag.py.
    tools/qdrant/combined_rag.py contains CombinedRAGTool(ContractTool).
    After BUG-17 fix: glob fallback fires (DEBUG log emitted), CombinedRAGTool returned.

    NOTE: Class name comparison used (not isinstance) to avoid dual-import module
    identity issues — see test_get_tool_resolves_flat_top_level_tool docstring.
    """
    from tools.unknown import Unknown

    stub = _make_agent_stub()
    with caplog.at_level(logging.DEBUG, logger="fingpt.agent.get_tool"):
        result = _call_get_tool_body(stub, "combined_rag")

    assert not isinstance(result, Unknown), (
        "get_tool('combined_rag') should NOT return Unknown — "
        "tools/qdrant/combined_rag.py exists; BUG-17 glob fallback must fire"
    )
    assert type(result).__name__ == "CombinedRAGTool", (
        f"Expected CombinedRAGTool, got {type(result).__name__}"
    )
    # BUG-17 fallback must emit a DEBUG log naming the resolved path
    assert any(
        "qdrant/combined_rag.py" in record.message
        for record in caplog.records
    ), (
        "BUG-17 DEBUG log not emitted — expected a message containing "
        "'qdrant/combined_rag.py' in fingpt.agent.get_tool logger"
    )


def test_get_tool_returns_unknown_for_truly_missing_tool():
    """get_tool() must return Unknown (not raise) for a tool name that doesn't exist.

    Baseline lock — Unknown fallback must still work after BUG-17 patch.
    The glob fallback must not raise when no file matches; it must let the
    existing Unknown-return path execute cleanly.
    """
    from tools.unknown import Unknown

    stub = _make_agent_stub()
    result = _call_get_tool_body(stub, "definitely_does_not_exist_xyzzy_12345")
    assert isinstance(result, Unknown), (
        "get_tool() must return Unknown for a tool name that doesn't exist anywhere — "
        "BUG-17 glob fallback must not raise; Unknown must be returned"
    )


def test_get_tool_flat_takes_precedence_over_subdir(caplog):
    """Flat tools/<name>.py wrapper takes precedence — glob fallback must NOT fire.

    When a tool resolves via the flat lookup (paths non-empty after
    subagents.get_paths), the BUG-17 glob branch must not execute.
    We verify this by asserting NO "BUG-17 subdir fallback" DEBUG log is emitted
    for a tool that resolves via the flat path.

    Uses ``response`` (tools/response.py) which:
      - Has a flat top-level file (resolves via flat lookup)
      - Has NO tools/*/response.py counterpart (unambiguous flat-only tool)

    The absence of the BUG-17 debug log confirms the fallback branch was
    skipped — which is the correct precedence behavior.

    NOTE: The plan calls for testing with a tool that exists in BOTH flat and subdir.
    In practice, the two BUG-14 flat wrappers (lookup_replay_artifact, fetch_replay_frame)
    both read os.environ["VM100_API_URL"] at import time — without that env var
    load_classes_from_file silently fails and returns []. We use ``response`` +
    log-absence check as a portable, env-agnostic precedence proof.
    """
    from tools.unknown import Unknown

    stub = _make_agent_stub()
    with caplog.at_level(logging.DEBUG, logger="fingpt.agent.get_tool"):
        result = _call_get_tool_body(stub, "response")

    # Flat lookup must succeed — NOT Unknown
    assert not isinstance(result, Unknown), (
        "get_tool('response') should NOT return Unknown — "
        "flat tools/response.py must resolve before glob fallback fires"
    )
    assert type(result).__name__ == "ResponseTool", (
        f"Expected ResponseTool (flat), got {type(result).__name__}"
    )
    # Glob fallback must NOT have fired — no BUG-17 debug log
    buglog = [r for r in caplog.records if "BUG-17 subdir fallback" in r.message]
    assert not buglog, (
        f"BUG-17 glob fallback fired for a flat tool — it must NOT fire when "
        f"flat lookup succeeds. Log: {[r.message for r in buglog]}"
    )
