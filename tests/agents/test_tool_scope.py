"""
Phase 44 Plan 02 — tool scope HARD enforcement tests.

Tests against core.agents.tool_scope + per-profile denial stubs in
agents/idea_agent/tools/ and agents/strategy_agent/tools/.

All xfail markers removed after Plan 44-02 Task 1 implements the module.

Test names MUST match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


def test_idea_agent_blocked():
    """
    check_tool_scope raises UnauthorizedToolError when idea_agent tries to
    use call_subordinate.

    HARD scope: idea_agent must NOT have call_subordinate access.
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError) as exc_info:
        check_tool_scope(agent_id="idea_agent", tool_name="call_subordinate")

    err = exc_info.value
    assert err.agent_id == "idea_agent"
    assert err.tool_name == "call_subordinate"
    assert "idea_agent" in str(err)
    assert "call_subordinate" in str(err)


def test_strategy_agent_blocked():
    """
    check_tool_scope raises UnauthorizedToolError when strategy_agent tries to
    use call_subordinate.
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError) as exc_info:
        check_tool_scope(agent_id="strategy_agent", tool_name="call_subordinate")

    err = exc_info.value
    assert err.agent_id == "strategy_agent"
    assert err.tool_name == "call_subordinate"


@pytest.mark.parametrize("tool_name", ["call_subordinate", "code_execution_tool"])
def test_sensitive_tools_blocked(tool_name):
    """
    Sensitive tools blocked for non-coordinator agents (parametrized).
    Both idea_agent and strategy_agent must be denied.
    """
    from core.agents.tool_scope import UnauthorizedToolError, check_tool_scope

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(agent_id="idea_agent", tool_name=tool_name)

    with pytest.raises(UnauthorizedToolError):
        check_tool_scope(agent_id="strategy_agent", tool_name=tool_name)


def test_coordinator_allowed():
    """
    agent_zero (Coordinator) is allowed to use call_subordinate.
    check_tool_scope must NOT raise.
    """
    from core.agents.tool_scope import check_tool_scope

    # Should not raise
    check_tool_scope(agent_id="agent_zero", tool_name="call_subordinate")
    check_tool_scope(agent_id="agent_zero", tool_name="code_execution_tool")


def test_is_tool_allowed_soft_tool():
    """
    is_tool_allowed returns True for soft-scoped tools (not in SENSITIVE_TOOLS)
    regardless of agent_id.
    """
    from core.agents.tool_scope import is_tool_allowed

    assert is_tool_allowed("idea_agent", "search_knowledge") is True
    assert is_tool_allowed("strategy_agent", "document_query") is True
    assert is_tool_allowed("idea_agent", "response") is True
    # Even for a completely unknown agent, soft tools return True
    assert is_tool_allowed("unknown_agent", "search_knowledge") is True


def test_is_tool_allowed_hard_tool_coordinator():
    """
    is_tool_allowed returns True for agent_zero using sensitive tools.
    """
    from core.agents.tool_scope import is_tool_allowed

    assert is_tool_allowed("agent_zero", "call_subordinate") is True
    assert is_tool_allowed("agent_zero", "code_execution_tool") is True


def test_is_tool_allowed_hard_tool_blocked():
    """
    is_tool_allowed returns False for idea_agent and strategy_agent on sensitive tools.
    """
    from core.agents.tool_scope import is_tool_allowed

    assert is_tool_allowed("idea_agent", "call_subordinate") is False
    assert is_tool_allowed("idea_agent", "code_execution_tool") is False
    assert is_tool_allowed("strategy_agent", "call_subordinate") is False
    assert is_tool_allowed("strategy_agent", "code_execution_tool") is False


def test_profile_to_agent_id_mapping():
    """
    PROFILE_TO_AGENT_ID["agent0"] == "agent_zero".
    Bridges filesystem profile name to routing identity (Research § 3).
    """
    from core.agents.tool_scope import PROFILE_TO_AGENT_ID

    assert PROFILE_TO_AGENT_ID["agent0"] == "agent_zero"
    assert PROFILE_TO_AGENT_ID["idea_agent"] == "idea_agent"
    assert PROFILE_TO_AGENT_ID["strategy_agent"] == "strategy_agent"
    assert PROFILE_TO_AGENT_ID["default"] == "default"


def test_sensitive_tools_registry():
    """
    SENSITIVE_TOOLS contains at minimum call_subordinate and code_execution_tool.
    """
    from core.agents.tool_scope import SENSITIVE_TOOLS

    assert "call_subordinate" in SENSITIVE_TOOLS
    assert "code_execution_tool" in SENSITIVE_TOOLS


def test_hard_allowed_tools_registry():
    """
    HARD_ALLOWED_TOOLS keys include agent_zero, idea_agent, strategy_agent.
    Idea and Strategy have empty frozensets (NO sensitive tools).
    """
    from core.agents.tool_scope import HARD_ALLOWED_TOOLS

    assert "agent_zero" in HARD_ALLOWED_TOOLS
    assert "call_subordinate" in HARD_ALLOWED_TOOLS["agent_zero"]
    assert "code_execution_tool" in HARD_ALLOWED_TOOLS["agent_zero"]

    assert "idea_agent" in HARD_ALLOWED_TOOLS
    assert len(HARD_ALLOWED_TOOLS["idea_agent"]) == 0

    assert "strategy_agent" in HARD_ALLOWED_TOOLS
    assert len(HARD_ALLOWED_TOOLS["strategy_agent"]) == 0


def _load_denial_stub(relative_path: str):
    """Load a denial stub module from the VM107 agents/ tree using importlib.

    Uses spec_from_file_location to bypass package-resolution issues in
    pytest-asyncio STRICT mode where sys.path might not be fully set up.
    """
    import importlib.util as ilu

    stub_path = _VM107_ROOT / relative_path
    spec = ilu.spec_from_file_location(relative_path.replace("/", "."), stub_path)
    mod = ilu.module_from_spec(spec)
    # Ensure VM107 is in sys.path before exec (helpers.tool import chain)
    if str(_VM107_ROOT) not in sys.path:
        sys.path.insert(0, str(_VM107_ROOT))
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_denial_stub_idea_call_subordinate():
    """
    Denial stub agents/idea_agent/tools/call_subordinate.py raises
    UnauthorizedToolError when execute() is awaited.

    Validates the per-profile override mechanism works end-to-end.
    """
    from core.agents.tool_scope import UnauthorizedToolError

    mod = _load_denial_stub("agents/idea_agent/tools/call_subordinate.py")
    Delegation = mod.Delegation

    stub = Delegation.__new__(Delegation)
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await stub.execute()

    assert exc_info.value.agent_id == "idea_agent"
    assert exc_info.value.tool_name == "call_subordinate"


@pytest.mark.asyncio
async def test_denial_stub_strategy_call_subordinate():
    """
    Denial stub agents/strategy_agent/tools/call_subordinate.py raises
    UnauthorizedToolError when execute() is awaited.
    """
    from core.agents.tool_scope import UnauthorizedToolError

    mod = _load_denial_stub("agents/strategy_agent/tools/call_subordinate.py")
    Delegation = mod.Delegation

    stub = Delegation.__new__(Delegation)
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await stub.execute()

    assert exc_info.value.agent_id == "strategy_agent"
    assert exc_info.value.tool_name == "call_subordinate"


@pytest.mark.asyncio
async def test_denial_stub_idea_code_execution():
    """
    Denial stub agents/idea_agent/tools/code_execution_tool.py raises
    UnauthorizedToolError when execute() is awaited.
    """
    from core.agents.tool_scope import UnauthorizedToolError

    mod = _load_denial_stub("agents/idea_agent/tools/code_execution_tool.py")
    CodeExecution = mod.CodeExecution

    stub = CodeExecution.__new__(CodeExecution)
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await stub.execute()

    assert exc_info.value.agent_id == "idea_agent"
    assert exc_info.value.tool_name == "code_execution_tool"


@pytest.mark.asyncio
async def test_denial_stub_strategy_code_execution():
    """
    Denial stub agents/strategy_agent/tools/code_execution_tool.py raises
    UnauthorizedToolError when execute() is awaited.
    """
    from core.agents.tool_scope import UnauthorizedToolError

    mod = _load_denial_stub("agents/strategy_agent/tools/code_execution_tool.py")
    CodeExecution = mod.CodeExecution

    stub = CodeExecution.__new__(CodeExecution)
    with pytest.raises(UnauthorizedToolError) as exc_info:
        await stub.execute()

    assert exc_info.value.agent_id == "strategy_agent"
    assert exc_info.value.tool_name == "code_execution_tool"
