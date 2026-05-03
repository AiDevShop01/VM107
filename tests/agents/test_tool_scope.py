"""
Phase 44 Wave 0 — tool scope HARD enforcement test scaffolds.

Tests against core.agents.tool_scope (created in Plan 44-02 Task 1).
All tests are xfail(strict=False) until that plan implements the module.

Test names MUST match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


@pytest.mark.xfail(reason="Implementation pending in Plan 44-02", strict=False)
def test_idea_agent_blocked():
    """
    Instantiating or calling the Delegation (call_subordinate) tool with
    agent profile idea_agent raises UnauthorizedToolError.

    HARD scope: idea_agent must NOT have call_subordinate access.
    Graduates in Plan 44-02 Task 1.
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(agent_id="idea_agent", tool_name="call_subordinate")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-02", strict=False)
def test_strategy_agent_blocked():
    """
    call_subordinate HARD-blocked for strategy_agent profile.

    Graduates in Plan 44-02 Task 1.
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(agent_id="strategy_agent", tool_name="call_subordinate")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-02", strict=False)
@pytest.mark.parametrize("tool_name", ["call_subordinate", "code_execution_tool"])
def test_sensitive_tools_blocked(tool_name):
    """
    Sensitive tools blocked for non-coordinator agents.

    Parametrized over call_subordinate and code_execution_tool.
    Graduates in Plan 44-02 Task 1.
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(agent_id="idea_agent", tool_name=tool_name)

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(agent_id="strategy_agent", tool_name=tool_name)


@pytest.mark.xfail(reason="Implementation pending in Plan 44-02", strict=False)
def test_coordinator_allowed():
    """
    agent_zero (Coordinator) is allowed to use call_subordinate.

    No exception should be raised.
    Graduates in Plan 44-02 Task 1.
    """
    from core.agents.tool_scope import check_tool_scope

    # Should not raise
    check_tool_scope(agent_id="agent_zero", tool_name="call_subordinate")
