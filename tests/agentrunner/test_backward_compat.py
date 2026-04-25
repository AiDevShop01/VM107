"""
Backward compatibility tests for AgentRunner extensions.

Tests verify:
- Extensions can be imported without errors
- Extensions have required execute() method
- Agent Zero works without runner (graceful degradation)
- No crashes when agent.get_data("runner") returns None
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from types import SimpleNamespace

import pytest


# Add extensions to path
extensions_path = os.path.join(os.path.dirname(__file__), "../../extensions/python")
sys.path.insert(0, extensions_path)


class TestExtensionStructure:
    """Test that extensions have required structure."""

    def test_runner_init_has_execute_method(self):
        """RunnerInit should have async execute() method."""
        from monologue_start._10_runner_init import RunnerInit
        ext_class = RunnerInit
        assert hasattr(ext_class, "execute")
        assert callable(getattr(ext_class, "execute"))

    def test_runner_state_check_has_execute_method(self):
        """RunnerStateCheck should have async execute() method."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck
        ext_class = RunnerStateCheck
        assert hasattr(ext_class, "execute")
        assert callable(getattr(ext_class, "execute"))

    def test_runner_step_update_has_execute_method(self):
        """RunnerStepUpdate should have async execute() method."""
        from message_loop_end._95_runner_step_update import RunnerStepUpdate
        ext_class = RunnerStepUpdate
        assert hasattr(ext_class, "execute")
        assert callable(getattr(ext_class, "execute"))

    def test_runner_cleanup_has_execute_method(self):
        """RunnerCleanup should have async execute() method."""
        from monologue_end._85_runner_cleanup import RunnerCleanup
        ext_class = RunnerCleanup
        assert hasattr(ext_class, "execute")
        assert callable(getattr(ext_class, "execute"))


class TestExtensionFileStructure:
    """Test that extension files exist in correct locations."""

    def test_runner_init_file_exists(self):
        """RunnerInit file should exist in monologue_start directory."""
        file_path = os.path.join(extensions_path, "monologue_start/_10_runner_init.py")
        assert os.path.exists(file_path)

    def test_runner_state_check_file_exists(self):
        """RunnerStateCheck file should exist in message_loop_start directory."""
        file_path = os.path.join(extensions_path, "message_loop_start/_05_runner_state_check.py")
        assert os.path.exists(file_path)

    def test_runner_step_update_file_exists(self):
        """RunnerStepUpdate file should exist in message_loop_end directory."""
        file_path = os.path.join(extensions_path, "message_loop_end/_95_runner_step_update.py")
        assert os.path.exists(file_path)

    def test_runner_cleanup_file_exists(self):
        """RunnerCleanup file should exist in monologue_end directory."""
        file_path = os.path.join(extensions_path, "monologue_end/_85_runner_cleanup.py")
        assert os.path.exists(file_path)


class TestGracefulDegradation:
    """Test that Agent Zero works without runner."""

    @pytest.fixture
    def mock_agent_without_runner(self):
        """Create mock agent without runner stored."""
        agent = SimpleNamespace(agent_name="test_agent")
        agent._data = {}
        agent.get_data = lambda key: agent._data.get(key)
        agent.set_data = lambda key, value: agent._data.__setitem__(key, value)
        return agent

    @pytest.mark.asyncio
    async def test_state_check_with_no_runner(self, mock_agent_without_runner):
        """StateCheck should not crash when runner is None."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck

        ext = RunnerStateCheck(agent=mock_agent_without_runner)
        loop_data = SimpleNamespace(iteration=1)

        # Should not raise
        await ext.execute(loop_data=loop_data)

        # Runner should still be None (no auto-creation)
        assert mock_agent_without_runner.get_data("runner") is None

    @pytest.mark.asyncio
    async def test_step_update_with_no_runner(self, mock_agent_without_runner):
        """StepUpdate should not crash when runner is None."""
        from message_loop_end._95_runner_step_update import RunnerStepUpdate

        ext = RunnerStepUpdate(agent=mock_agent_without_runner)
        loop_data = SimpleNamespace(iteration=1)

        # Should not raise
        await ext.execute(loop_data=loop_data)

        # Runner should still be None
        assert mock_agent_without_runner.get_data("runner") is None

    @pytest.mark.asyncio
    async def test_cleanup_with_no_runner(self, mock_agent_without_runner):
        """Cleanup should not crash when runner is None."""
        from monologue_end._85_runner_cleanup import RunnerCleanup

        ext = RunnerCleanup(agent=mock_agent_without_runner)

        # Should not raise
        await ext.execute()

        # Runner should still be None
        assert mock_agent_without_runner.get_data("runner") is None


class TestExtensionInitialization:
    """Test extension initialization with agent parameter."""

    def test_extensions_accept_agent_parameter(self):
        """All extensions should accept agent parameter in __init__."""
        from monologue_start._10_runner_init import RunnerInit
        from message_loop_start._05_runner_state_check import RunnerStateCheck
        from message_loop_end._95_runner_step_update import RunnerStepUpdate
        from monologue_end._85_runner_cleanup import RunnerCleanup

        agent = SimpleNamespace(agent_name="test")

        # Should not raise
        RunnerInit(agent=agent)
        RunnerStateCheck(agent=agent)
        RunnerStepUpdate(agent=agent)
        RunnerCleanup(agent=agent)

    def test_extensions_store_agent_reference(self):
        """Extensions should store agent reference from __init__."""
        from monologue_start._10_runner_init import RunnerInit

        agent = SimpleNamespace(agent_name="test")
        ext = RunnerInit(agent=agent)

        # Extension should have agent attribute (from Extension base class)
        assert hasattr(ext, "agent")
        assert ext.agent == agent
