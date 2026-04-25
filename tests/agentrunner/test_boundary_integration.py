"""
Integration tests for ExecutionBoundary with AgentRunner.

Tests verify that boundary violations trigger proper state transitions in AgentRunner.

Coverage:
- Step limit enforcement
- Token limit enforcement
- Cost limit enforcement
- Time limit enforcement
- Warning status (doesn't stop execution)
- NoOpBoundary backward compatibility
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.boundary.budget_tracker import InMemoryBudgetTracker
from core.boundary.config_resolver import ResolvedBoundaryConfig
from core.boundary.execution_boundary import ExecutionBoundary
from core.execution_context import BoundaryStatus, ExecutionContext
from core.interfaces import NoOpBoundary, NoOpProgressLedger, NoOpStallDetector, NoOpTaskLedger
from core.state_machine import AgentState


@pytest.fixture
def mock_agent():
    """Create a simple mock agent object."""
    context = SimpleNamespace(id="test_ctx_1")
    agent = SimpleNamespace(agent_name="test_agent", context=context)
    return agent


@pytest.fixture
def budget_tracker():
    """Create in-memory budget tracker."""
    return InMemoryBudgetTracker()


@pytest.fixture
def boundary_config():
    """Create test boundary config with reasonable limits."""
    return ResolvedBoundaryConfig(
        max_steps=10,
        max_tokens=1000,
        max_cost_usd=1.0,
        max_execution_time_sec=60,
        daily_budget_usd=10.0,
    )


@pytest.fixture
def execution_boundary(boundary_config, budget_tracker):
    """Create ExecutionBoundary for testing."""
    return ExecutionBoundary(
        config=boundary_config,
        budget_tracker=budget_tracker,
        agent_name="test_agent",
    )


@pytest.fixture
def runner_with_boundary(mock_agent, execution_boundary):
    """Create AgentRunner with real ExecutionBoundary."""
    return AgentRunner(agent=mock_agent, boundary=execution_boundary)


class TestExecutionBoundaryIntegration:
    """Test ExecutionBoundary integration with AgentRunner."""

    @pytest.mark.asyncio
    async def test_execution_boundary_with_runner(self, runner_with_boundary):
        """AgentRunner can be created with ExecutionBoundary."""
        assert runner_with_boundary.state == AgentState.IDLE
        assert runner_with_boundary.boundary is not None
        assert isinstance(runner_with_boundary.boundary, ExecutionBoundary)

        # Start runner
        await runner_with_boundary.start()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Manually push context to near limits
        runner_with_boundary.execution_context.step_count = 9  # 90% of max_steps=10
        runner_with_boundary.execution_context.token_count = 900  # 90% of max_tokens=1000
        runner_with_boundary.execution_context.cost_usd = 0.9  # 90% of max_cost_usd=1.0

        # run_step should still succeed (not at limit yet)
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Push past limit
        runner_with_boundary.execution_context.step_count = 11  # Exceeds max_steps=10

        # Next step should trigger FAILED transition
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.FAILED


class TestStepLimitEnforcement:
    """Test step limit enforcement."""

    @pytest.mark.asyncio
    async def test_execution_boundary_step_limit_fails_runner(self, runner_with_boundary):
        """Step limit violation should transition runner to FAILED."""
        # Start runner
        await runner_with_boundary.start()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Set step count at limit
        runner_with_boundary.execution_context.step_count = 10  # max_steps=10

        # run_step should detect exceeded state and fail runner
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.FAILED

    @pytest.mark.asyncio
    async def test_step_limit_exceeded_reason(self, runner_with_boundary):
        """FAILED state should include exceeded reason in logs."""
        await runner_with_boundary.start()

        # Exceed step limit
        runner_with_boundary.execution_context.step_count = 11

        # Check boundary status
        status = await runner_with_boundary.boundary.check(runner_with_boundary.execution_context)
        assert status.is_exceeded()
        assert status == BoundaryStatus.STEP_LIMIT_EXCEEDED


class TestTokenLimitEnforcement:
    """Test token limit enforcement."""

    @pytest.mark.asyncio
    async def test_execution_boundary_token_limit_fails_runner(self, runner_with_boundary):
        """Token limit violation should transition runner to FAILED."""
        await runner_with_boundary.start()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Set token count at limit
        runner_with_boundary.execution_context.token_count = 1000  # max_tokens=1000

        # run_step should detect exceeded state and fail runner
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.FAILED

    @pytest.mark.asyncio
    async def test_token_limit_exceeded_reason(self, runner_with_boundary):
        """Token limit exceeded should return correct status."""
        await runner_with_boundary.start()

        # Exceed token limit
        runner_with_boundary.execution_context.token_count = 1001

        # Check boundary status
        status = await runner_with_boundary.boundary.check(runner_with_boundary.execution_context)
        assert status.is_exceeded()
        assert status == BoundaryStatus.TOKEN_LIMIT_EXCEEDED


class TestCostLimitEnforcement:
    """Test cost limit enforcement."""

    @pytest.mark.asyncio
    async def test_execution_boundary_cost_limit_fails_runner(self, runner_with_boundary):
        """Cost limit violation should transition runner to FAILED."""
        await runner_with_boundary.start()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Set cost at limit
        runner_with_boundary.execution_context.cost_usd = 1.0  # max_cost_usd=1.0

        # run_step should detect exceeded state and fail runner
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.FAILED

    @pytest.mark.asyncio
    async def test_cost_limit_exceeded_reason(self, runner_with_boundary):
        """Cost limit exceeded should return correct status."""
        await runner_with_boundary.start()

        # Exceed cost limit
        runner_with_boundary.execution_context.cost_usd = 1.01

        # Check boundary status
        status = await runner_with_boundary.boundary.check(runner_with_boundary.execution_context)
        assert status.is_exceeded()
        assert status == BoundaryStatus.COST_LIMIT_EXCEEDED


class TestTimeLimitEnforcement:
    """Test time limit enforcement."""

    @pytest.mark.asyncio
    async def test_execution_boundary_time_limit_fails_runner(self, runner_with_boundary):
        """Time limit violation should transition runner to FAILED."""
        await runner_with_boundary.start()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Manipulate start time to simulate time passage
        # max_time_seconds=60, so set start_time to 61 seconds ago
        runner_with_boundary.execution_context.start_time = time.time() - 61

        # run_step should detect exceeded state and fail runner
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.FAILED

    @pytest.mark.asyncio
    async def test_time_limit_exceeded_reason(self, runner_with_boundary):
        """Time limit exceeded should return correct status."""
        await runner_with_boundary.start()

        # Exceed time limit
        runner_with_boundary.execution_context.start_time = time.time() - 61

        # Check boundary status
        status = await runner_with_boundary.boundary.check(runner_with_boundary.execution_context)
        assert status.is_exceeded()
        assert status == BoundaryStatus.TIME_LIMIT_EXCEEDED


class TestNoOpBoundaryBackwardCompat:
    """Test NoOpBoundary backward compatibility."""

    @pytest.mark.asyncio
    async def test_noopboundary_still_works(self, mock_agent):
        """AgentRunner with NoOpBoundary always returns OK."""
        runner = AgentRunner(agent=mock_agent, boundary=NoOpBoundary())

        await runner.start()
        assert runner.state == AgentState.RUNNING

        # Push metrics way past any reasonable limit
        runner.execution_context.step_count = 999999
        runner.execution_context.token_count = 999999
        runner.execution_context.cost_usd = 999999.0
        runner.execution_context.start_time = time.time() - 999999

        # Check boundary (should always return OK)
        status = await runner.boundary.check(runner.execution_context)
        assert status == BoundaryStatus.OK

        # run_step should succeed
        await runner.run_step()
        assert runner.state == AgentState.RUNNING


class TestWarningStatus:
    """Test warning status doesn't stop execution."""

    @pytest.mark.asyncio
    async def test_warning_does_not_stop_execution(self, runner_with_boundary):
        """Warning status should not stop execution."""
        await runner_with_boundary.start()
        assert runner_with_boundary.state == AgentState.RUNNING

        # Set metrics at 80% threshold (hardcoded in ExecutionBoundary)
        runner_with_boundary.execution_context.step_count = 8  # 80% of max_steps=10
        runner_with_boundary.execution_context.token_count = 800  # 80% of max_tokens=1000
        runner_with_boundary.execution_context.cost_usd = 0.8  # 80% of max_cost_usd=1.0

        # Check boundary (should return WARNING)
        status = await runner_with_boundary.boundary.check(runner_with_boundary.execution_context)
        assert status == BoundaryStatus.WARNING

        # run_step should still succeed
        await runner_with_boundary.run_step()
        assert runner_with_boundary.state == AgentState.RUNNING

    @pytest.mark.asyncio
    async def test_warning_logs_message(self, runner_with_boundary):
        """Warning status should log message (not tested here, validated manually)."""
        await runner_with_boundary.start()

        # Set metrics at warning threshold
        runner_with_boundary.execution_context.token_count = 801  # >80% of 1000

        # Check status
        status = await runner_with_boundary.boundary.check(runner_with_boundary.execution_context)
        assert status == BoundaryStatus.WARNING

        # Actual log output would be verified in integration or E2E tests
        # Unit test just verifies WARNING status is returned
