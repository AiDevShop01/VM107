"""Phase 47.2-06 — graduated denial-stub tests for the 9 Wave 3 trade-context tools.

Pattern mirrors Phase 44 `tests/agents/test_tool_scope.py::test_denial_stub_*`:
  - Load each per-profile denial stub via importlib.spec_from_file_location
    (bypasses package-resolution issues in pytest-asyncio STRICT mode)
  - Instantiate via `Cls.__new__(Cls)` (skips Tool.__init__ which needs an Agent)
  - Await `.execute()` and assert UnauthorizedToolError is raised with the
    expected agent_id + tool_name

Coverage:
  - test_agent_zero_resolves_all  -> NO per-profile stub exists for agent_zero;
                                      the global tool at tools/<name>.py is the
                                      file that resolves. Verified by checking
                                      `agents/agent0/tools/<name>.py` does NOT
                                      exist (would intercept) and the global
                                      tool file IS present.
  - test_idea_agent_blocked       -> 9 parametrised cases, one per Wave 3 tool
  - test_strategy_agent_blocked   -> 9 parametrised cases, one per Wave 3 tool

Total: 27 test cases (9 per spec × 3 specs).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

WAVE_3_TOOLS = [
    "get_trade_context",
    "get_primitives",
    "get_liquidity_context",
    "get_strategy_definition",
    "get_macro_context",
    "get_news_context",
    "get_regime_context",
    "get_sentiment_context",
    "get_performance_history",
]

# CamelCase class names matching the global tool class names
# (tool dispatch resolves by FILENAME, not class name — see RESEARCH Critical
# Finding #4. Same class name keeps the per-profile stub trivially recognizable.)
TOOL_CLASS_NAMES = {
    "get_trade_context": "GetTradeContext",
    "get_primitives": "GetPrimitives",
    "get_liquidity_context": "GetLiquidityContext",
    "get_strategy_definition": "GetStrategyDefinition",
    "get_macro_context": "GetMacroContext",
    "get_news_context": "GetNewsContext",
    "get_regime_context": "GetRegimeContext",
    "get_sentiment_context": "GetSentimentContext",
    "get_performance_history": "GetPerformanceHistory",
}


def _load_denial_stub(relative_path: str):
    """Load a denial stub module from the VM107 agents/ tree using importlib.

    Mirrors Phase 44 `tests/agents/test_tool_scope.py::_load_denial_stub` —
    bypasses package-resolution issues in pytest-asyncio STRICT mode where
    sys.path might not be fully set up.
    """
    import importlib.util as ilu

    stub_path = _VM107_ROOT / relative_path
    spec = ilu.spec_from_file_location(relative_path.replace("/", "."), stub_path)
    mod = ilu.module_from_spec(spec)
    if str(_VM107_ROOT) not in sys.path:
        sys.path.insert(0, str(_VM107_ROOT))
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Spec 1 — Coordinator (agent_zero) resolves all 9 tools via the global path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tool_name", WAVE_3_TOOLS)
def test_agent_zero_resolves_all(tool_name):
    """Coordinator (agent_zero profile) sees the global tool file at tools/<name>.py.

    For agent_zero, `subagents.get_paths` resolves to:
      1. agents/agent0/tools/<name>.py  -- MUST NOT exist (would intercept)
      2. tools/<name>.py                -- MUST exist (Plans 04+05 shipped these)

    No per-profile stub exists for agent_zero, so the global tool is the one
    that resolves. This preserves the SOFT-scope on the Coordinator.
    """
    global_tool = _VM107_ROOT / "tools" / f"{tool_name}.py"
    coord_override = _VM107_ROOT / "agents" / "agent0" / "tools" / f"{tool_name}.py"

    assert global_tool.is_file(), (
        f"Global tool tools/{tool_name}.py missing — Plans 04+05 must ship it"
    )
    assert not coord_override.is_file(), (
        f"agents/agent0/tools/{tool_name}.py exists — would intercept Coordinator "
        f"and break SOFT-scope on agent_zero. Phase 47.2 lock: per-profile stubs "
        f"only on idea_agent / strategy_agent."
    )


# ---------------------------------------------------------------------------
# Spec 2 — idea_agent profile is HARD-blocked on every Wave 3 tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", WAVE_3_TOOLS)
async def test_idea_agent_blocked(tool_name):
    """idea_agent denial stub at agents/idea_agent/tools/<tool>.py raises
    UnauthorizedToolError when execute() is awaited.

    Validates the per-profile override mechanism works for each of the 9 tools.
    """
    from core.agents.tool_scope import UnauthorizedToolError

    mod = _load_denial_stub(f"agents/idea_agent/tools/{tool_name}.py")
    cls = getattr(mod, TOOL_CLASS_NAMES[tool_name])

    stub = cls.__new__(cls)  # skip Tool.__init__
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await stub.execute()

    assert exc_info.value.agent_id == "idea_agent"
    assert exc_info.value.tool_name == tool_name


# ---------------------------------------------------------------------------
# Spec 3 — strategy_agent profile is HARD-blocked on every Wave 3 tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", WAVE_3_TOOLS)
async def test_strategy_agent_blocked(tool_name):
    """strategy_agent denial stub at agents/strategy_agent/tools/<tool>.py raises
    UnauthorizedToolError when execute() is awaited.

    Validates the per-profile override mechanism works for each of the 9 tools.
    """
    from core.agents.tool_scope import UnauthorizedToolError

    mod = _load_denial_stub(f"agents/strategy_agent/tools/{tool_name}.py")
    cls = getattr(mod, TOOL_CLASS_NAMES[tool_name])

    stub = cls.__new__(cls)  # skip Tool.__init__
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await stub.execute()

    assert exc_info.value.agent_id == "strategy_agent"
    assert exc_info.value.tool_name == tool_name
