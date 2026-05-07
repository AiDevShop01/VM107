"""Phase 47.2-01 Wave 0 — xfail stubs for the 18 denial-stub tool scope checks.

Target module: core.agents.tool_scope (extension)
Plans 04+05 ship the 9 tools, then Plan 06 wires them into tool_scope.py
so the Coordinator (`agent_zero` profile) resolves all of them, while
`idea_agent` and `strategy_agent` profiles raise UnauthorizedToolError.

18 denial stubs = 9 tools × 2 blocked profiles.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

_TOOL_NAMES = [
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


@pytest.mark.xfail(
    reason="Wave 0 stub — Plans 04+05 ship the 9 tools and Plan 06 registers scoping",
    strict=False,
)
@pytest.mark.parametrize("tool_name", _TOOL_NAMES)
def test_agent_zero_resolves_all(tool_name):
    """For each of the 9 tools, agent.get_tool(name, agent_id='agent_zero') succeeds."""
    from core.agents.tool_scope import check_tool_scope  # noqa: F401

    pytest.fail(
        f"Wave 0 stub — Plan 06 registers {tool_name} for agent_zero soft scope"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 06 wires HARD denial for idea_agent profile",
    strict=False,
)
@pytest.mark.parametrize("tool_name", _TOOL_NAMES)
def test_idea_agent_blocked(tool_name):
    """idea_agent calling each tool raises UnauthorizedToolError."""
    from core.agents.tool_scope import (  # noqa: F401
        UnauthorizedToolError,
        check_tool_scope,
    )

    pytest.fail(
        f"Wave 0 stub — Plan 06 hard-blocks {tool_name} for idea_agent profile"
    )


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 06 wires HARD denial for strategy_agent profile",
    strict=False,
)
@pytest.mark.parametrize("tool_name", _TOOL_NAMES)
def test_strategy_agent_blocked(tool_name):
    """strategy_agent calling each tool raises UnauthorizedToolError."""
    from core.agents.tool_scope import (  # noqa: F401
        UnauthorizedToolError,
        check_tool_scope,
    )

    pytest.fail(
        f"Wave 0 stub — Plan 06 hard-blocks {tool_name} for strategy_agent profile"
    )
