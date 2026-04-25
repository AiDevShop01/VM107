"""
Tests for AgentRunner extension integration.

Tests cover:
- Extension execute() methods in isolation
- Graceful handling of missing agent
- Graceful handling of missing runner
- State transitions via extensions
- Execution context updates

NOTE: Extensions are imported dynamically in tests to avoid loading
Agent Zero dependencies at import time.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

import pytest

from core.agent_runner import AgentRunner
from core.state_machine import AgentState

# Add extensions to path (but don't import yet)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../extensions/python"))


@pytest.fixture
def mock_agent():
    """Create a mock agent with get_data/set_data methods."""
    context = SimpleNamespace(id="test_ctx_1")
    agent = SimpleNamespace(agent_name="test_agent", context=context)
    agent._data = {}
    agent.get_data = lambda key: agent._data.get(key)
    agent.set_data = lambda key, value: agent._data.__setitem__(key, value)
    return agent


@pytest.fixture
def mock_loop_data():
    """Create a mock LoopData object."""
    return SimpleNamespace(iteration=5)


class TestRunnerInit:
    """Test monologue_start/_10_runner_init.py extension."""

    @pytest.mark.asyncio
    async def test_creates_and_stores_runner(self, mock_agent):
        """RunnerInit should create AgentRunner and store on agent."""
        from monologue_start._10_runner_init import RunnerInit

        ext = RunnerInit(agent=mock_agent)
        await ext.execute()

        runner = mock_agent.get_data("runner")
        assert runner is not None
        assert isinstance(runner, AgentRunner)
        assert runner.agent == mock_agent

    @pytest.mark.asyncio
    async def test_transitions_to_running(self, mock_agent):
        """RunnerInit should transition runner to RUNNING state."""
        from monologue_start._10_runner_init import RunnerInit

        ext = RunnerInit(agent=mock_agent)
        await ext.execute()

        runner = mock_agent.get_data("runner")
        assert runner.state == AgentState.RUNNING

    @pytest.mark.asyncio
    async def test_reuses_existing_runner(self, mock_agent):
        """RunnerInit should not recreate if runner already exists."""
        from monologue_start._10_runner_init import RunnerInit

        # Create first runner
        ext = RunnerInit(agent=mock_agent)
        await ext.execute()
        runner1 = mock_agent.get_data("runner")

        # Run again
        await ext.execute()
        runner2 = mock_agent.get_data("runner")

        # Should be the same instance
        assert runner1 is runner2

    @pytest.mark.asyncio
    async def test_handles_none_agent_gracefully(self):
        """RunnerInit should handle None agent without error."""
        from monologue_start._10_runner_init import RunnerInit

        ext = RunnerInit(agent=None)
        # Should not raise
        await ext.execute()


class TestRunnerStateCheck:
    """Test message_loop_start/_05_runner_state_check.py extension."""

    @pytest.mark.asyncio
    async def test_updates_loop_iterations_when_running(self, mock_agent, mock_loop_data):
        """StateCheck should update execution context with loop iteration."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck

        # Setup runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        mock_agent.set_data("runner", runner)

        # Execute extension
        ext = RunnerStateCheck(agent=mock_agent)
        await ext.execute(loop_data=mock_loop_data)

        # Verify context updated
        assert runner.execution_context.loop_iterations == 5

    @pytest.mark.asyncio
    async def test_logs_when_paused(self, mock_agent, mock_loop_data):
        """StateCheck should log and return when runner is PAUSED."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck

        # Setup paused runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        await runner.pause()
        mock_agent.set_data("runner", runner)

        # Execute extension (should not error)
        ext = RunnerStateCheck(agent=mock_agent)
        await ext.execute(loop_data=mock_loop_data)

        # State should still be paused (no changes)
        assert runner.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_handles_cancelled_state(self, mock_agent, mock_loop_data):
        """StateCheck should handle CANCELLED state without error."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck

        # Setup cancelled runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        await runner.cancel()
        mock_agent.set_data("runner", runner)

        # Execute extension (should not error)
        ext = RunnerStateCheck(agent=mock_agent)
        await ext.execute(loop_data=mock_loop_data)

        # State should still be cancelled
        assert runner.state == AgentState.CANCELLED

    @pytest.mark.asyncio
    async def test_handles_missing_runner_gracefully(self, mock_agent, mock_loop_data):
        """StateCheck should handle missing runner without error."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck

        # No runner stored on agent
        ext = RunnerStateCheck(agent=mock_agent)
        # Should not raise
        await ext.execute(loop_data=mock_loop_data)

    @pytest.mark.asyncio
    async def test_handles_none_agent_gracefully(self, mock_loop_data):
        """StateCheck should handle None agent without error."""
        from message_loop_start._05_runner_state_check import RunnerStateCheck

        ext = RunnerStateCheck(agent=None)
        # Should not raise
        await ext.execute(loop_data=mock_loop_data)


class TestRunnerStepUpdate:
    """Test message_loop_end/_95_runner_step_update.py extension."""

    @pytest.mark.asyncio
    async def test_increments_step_count(self, mock_agent, mock_loop_data):
        """StepUpdate should increment step_count in execution context."""
        from message_loop_end._95_runner_step_update import RunnerStepUpdate

        # Setup runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        mock_agent.set_data("runner", runner)

        initial_steps = runner.execution_context.step_count

        # Execute extension
        ext = RunnerStepUpdate(agent=mock_agent)
        await ext.execute(loop_data=mock_loop_data)

        # Verify step count incremented
        assert runner.execution_context.step_count == initial_steps + 1

    @pytest.mark.asyncio
    async def test_handles_missing_runner_gracefully(self, mock_agent, mock_loop_data):
        """StepUpdate should handle missing runner without error."""
        from message_loop_end._95_runner_step_update import RunnerStepUpdate

        # No runner stored on agent
        ext = RunnerStepUpdate(agent=mock_agent)
        # Should not raise
        await ext.execute(loop_data=mock_loop_data)

    @pytest.mark.asyncio
    async def test_handles_none_agent_gracefully(self, mock_loop_data):
        """StepUpdate should handle None agent without error."""
        from message_loop_end._95_runner_step_update import RunnerStepUpdate

        ext = RunnerStepUpdate(agent=None)
        # Should not raise
        await ext.execute(loop_data=mock_loop_data)


class TestRunnerCleanup:
    """Test monologue_end/_85_runner_cleanup.py extension."""

    @pytest.mark.asyncio
    async def test_transitions_running_to_complete(self, mock_agent):
        """Cleanup should transition RUNNING -> COMPLETE."""
        from monologue_end._85_runner_cleanup import RunnerCleanup

        # Setup running runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        mock_agent.set_data("runner", runner)

        # Execute extension
        ext = RunnerCleanup(agent=mock_agent)
        await ext.execute()

        # Verify transitioned to complete
        assert runner.state == AgentState.COMPLETE

    @pytest.mark.asyncio
    async def test_transitions_paused_to_complete(self, mock_agent):
        """Cleanup should transition PAUSED -> COMPLETE."""
        from monologue_end._85_runner_cleanup import RunnerCleanup

        # Setup paused runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        await runner.pause()
        mock_agent.set_data("runner", runner)

        # Execute extension
        ext = RunnerCleanup(agent=mock_agent)
        await ext.execute()

        # Verify transitioned to complete
        assert runner.state == AgentState.COMPLETE

    @pytest.mark.asyncio
    async def test_cleans_up_terminal_states(self, mock_agent):
        """Cleanup should clean up even if already in terminal state."""
        from monologue_end._85_runner_cleanup import RunnerCleanup

        # Setup cancelled runner
        runner = AgentRunner(mock_agent)
        await runner.start()
        await runner.cancel()
        mock_agent.set_data("runner", runner)

        # Execute extension (should not error)
        ext = RunnerCleanup(agent=mock_agent)
        await ext.execute()

        # State should still be cancelled
        assert runner.state == AgentState.CANCELLED

    @pytest.mark.asyncio
    async def test_handles_missing_runner_gracefully(self, mock_agent):
        """Cleanup should handle missing runner without error."""
        from monologue_end._85_runner_cleanup import RunnerCleanup

        # No runner stored on agent
        ext = RunnerCleanup(agent=mock_agent)
        # Should not raise
        await ext.execute()

    @pytest.mark.asyncio
    async def test_handles_none_agent_gracefully(self):
        """Cleanup should handle None agent without error."""
        from monologue_end._85_runner_cleanup import RunnerCleanup

        ext = RunnerCleanup(agent=None)
        # Should not raise
        await ext.execute()
