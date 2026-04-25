"""
Tests for AgentRunner execution engine.

Tests cover:
- Lifecycle transitions (start, pause, resume, cancel, complete, fail, reset)
- Error handling (invalid transitions, boundary exceeded)
- Structured logging (state transitions)
- Performance (state check, transition overhead)
- Interface integration (no-op defaults)
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_runner import AgentRunner
from core.execution_context import BoundaryStatus
from core.interfaces import NoOpBoundary, NoOpProgressLedger, NoOpStallDetector, NoOpTaskLedger
from core.state_machine import AgentState, InvalidTransitionError


@pytest.fixture
def mock_agent():
    """Create a simple mock agent object."""
    context = SimpleNamespace(id="test_ctx_1")
    agent = SimpleNamespace(agent_name="test_agent", context=context)
    return agent


@pytest.fixture
def runner(mock_agent):
    """Create an AgentRunner instance with no-op interfaces."""
    return AgentRunner(mock_agent)


class TestLifecycle:
    """Test basic lifecycle transitions."""

    @pytest.mark.asyncio
    async def test_starts_in_idle_state(self, runner):
        """AgentRunner should start in IDLE state."""
        assert runner.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_start_transitions_to_running(self, runner):
        """start() should transition IDLE -> RUNNING."""
        await runner.start()
        assert runner.state == AgentState.RUNNING

    @pytest.mark.asyncio
    async def test_start_from_non_idle_raises_error(self, runner):
        """start() from non-IDLE state should raise InvalidTransitionError."""
        await runner.start()  # Now in RUNNING
        with pytest.raises(InvalidTransitionError) as exc_info:
            await runner.start()
        assert exc_info.value.from_state == AgentState.RUNNING
        assert exc_info.value.to_state == AgentState.RUNNING

    @pytest.mark.asyncio
    async def test_complete_transitions_running_to_complete(self, runner):
        """complete() should transition RUNNING -> COMPLETE."""
        await runner.start()
        await runner.complete()
        assert runner.state == AgentState.COMPLETE

    @pytest.mark.asyncio
    async def test_fail_transitions_running_to_failed(self, runner):
        """fail(reason) should transition RUNNING -> FAILED."""
        await runner.start()
        await runner.fail("Test failure")
        assert runner.state == AgentState.FAILED

    @pytest.mark.asyncio
    async def test_reset_transitions_failed_to_idle(self, runner):
        """reset() should transition FAILED -> IDLE."""
        await runner.start()
        await runner.fail("Test failure")
        await runner.reset()
        assert runner.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_reset_transitions_complete_to_idle(self, runner):
        """reset() should transition COMPLETE -> IDLE."""
        await runner.start()
        await runner.complete()
        await runner.reset()
        assert runner.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_reset_clears_execution_context(self, runner):
        """reset() should reset execution context to defaults."""
        await runner.start()
        runner.execution_context.step_count = 10
        runner.execution_context.token_count = 500
        await runner.fail("Test")
        await runner.reset()
        assert runner.execution_context.step_count == 0
        assert runner.execution_context.token_count == 0
        assert runner.execution_context.task_id == ""


class TestPauseResume:
    """Test pause/resume functionality."""

    @pytest.mark.asyncio
    async def test_pause_transitions_running_to_paused(self, runner):
        """pause() should transition RUNNING -> PAUSED."""
        await runner.start()
        await runner.pause()
        assert runner.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_resume_transitions_paused_to_running(self, runner):
        """resume() should transition PAUSED -> RUNNING."""
        await runner.start()
        await runner.pause()
        await runner.resume()
        assert runner.state == AgentState.RUNNING

    @pytest.mark.asyncio
    async def test_resume_preserves_step_count(self, runner):
        """resume() should preserve execution_context.step_count."""
        await runner.start()
        runner.execution_context.step_count = 5
        await runner.pause()
        await runner.resume()
        assert runner.execution_context.step_count == 5

    @pytest.mark.asyncio
    async def test_resume_preserves_token_count(self, runner):
        """resume() should preserve execution_context.token_count."""
        await runner.start()
        runner.execution_context.token_count = 100
        await runner.pause()
        await runner.resume()
        assert runner.execution_context.token_count == 100


class TestCancel:
    """Test cancel functionality."""

    @pytest.mark.asyncio
    async def test_cancel_from_running_transitions_to_cancelled(self, runner):
        """cancel() should transition RUNNING -> CANCELLED."""
        await runner.start()
        await runner.cancel()
        assert runner.state == AgentState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_from_paused_transitions_to_cancelled(self, runner):
        """cancel() should transition PAUSED -> CANCELLED."""
        await runner.start()
        await runner.pause()
        await runner.cancel()
        assert runner.state == AgentState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_from_idle_raises_error(self, runner):
        """cancel() from IDLE should raise InvalidTransitionError."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            await runner.cancel()
        assert exc_info.value.from_state == AgentState.IDLE
        assert exc_info.value.to_state == AgentState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_calls_cleanup(self, runner):
        """cancel() should call cleanup()."""
        await runner.start()
        await runner.cancel()
        # cleanup should set _cleaned_up flag
        assert runner._cleaned_up is True


class TestStructuredLogging:
    """Test structured JSON logging for state transitions."""

    @pytest.mark.asyncio
    async def test_transition_logs_structured_json(self, runner, mock_agent):
        """transition() should log structured JSON with all required fields."""
        with patch("core.agent_runner.logger") as mock_logger:
            await runner.start()

            # Get the log call
            assert mock_logger.info.called
            log_message = mock_logger.info.call_args[0][0]

            # Parse JSON
            log_data = json.loads(log_message)

            # Verify all required fields
            assert log_data["event"] == "state_transition"
            assert log_data["from_state"] == "idle"
            assert log_data["to_state"] == "running"
            assert "reason" in log_data
            assert "timestamp" in log_data
            assert log_data["agent_id"] == "test_agent"
            assert log_data["context_id"] == "test_ctx_1"

    @pytest.mark.asyncio
    async def test_transition_timestamp_is_iso8601(self, runner):
        """transition() should log timestamp in ISO 8601 format."""
        with patch("core.agent_runner.logger") as mock_logger:
            await runner.start()
            log_message = mock_logger.info.call_args[0][0]
            log_data = json.loads(log_message)

            # Verify ISO 8601 format (contains 'T' and 'Z')
            assert "T" in log_data["timestamp"]
            assert log_data["timestamp"].endswith("Z")


class TestRunStep:
    """Test run_step() method."""

    @pytest.mark.asyncio
    async def test_run_step_returns_none_if_not_running(self, runner):
        """run_step() should return None if state is not RUNNING."""
        result = await runner.run_step()
        assert result is None

    @pytest.mark.asyncio
    async def test_run_step_increments_step_count(self, runner):
        """run_step() should increment execution_context.step_count."""
        await runner.start()
        initial_count = runner.execution_context.step_count
        await runner.run_step()
        assert runner.execution_context.step_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_run_step_checks_boundary(self, runner):
        """run_step() should call boundary.check()."""
        mock_boundary = MagicMock()
        mock_boundary.check = AsyncMock(return_value=BoundaryStatus.OK)
        runner.boundary = mock_boundary

        await runner.start()
        await runner.run_step()

        mock_boundary.check.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_step_transitions_to_failed_on_boundary_exceeded(self, runner):
        """run_step() should transition to FAILED if boundary status is EXCEEDED."""
        mock_boundary = MagicMock()
        mock_boundary.check = AsyncMock(return_value=BoundaryStatus.EXCEEDED)
        runner.boundary = mock_boundary

        await runner.start()
        await runner.run_step()

        assert runner.state == AgentState.FAILED

    @pytest.mark.asyncio
    async def test_run_step_calls_stall_detector(self, runner):
        """run_step() should call stall_detector.check()."""
        mock_stall_detector = MagicMock()
        mock_stall_detector.check = AsyncMock(return_value=False)
        runner.stall_detector = mock_stall_detector

        await runner.start()
        await runner.run_step()

        mock_stall_detector.check.assert_called_once()


class TestInterfaceDefaults:
    """Test no-op interface defaults."""

    @pytest.mark.asyncio
    async def test_constructor_accepts_none_for_task_ledger(self, mock_agent):
        """Constructor should accept None for task_ledger (defaults to NoOpTaskLedger)."""
        runner = AgentRunner(mock_agent, task_ledger=None)
        assert isinstance(runner.task_ledger, NoOpTaskLedger)

    @pytest.mark.asyncio
    async def test_constructor_accepts_none_for_progress_ledger(self, mock_agent):
        """Constructor should accept None for progress_ledger (defaults to NoOpProgressLedger)."""
        runner = AgentRunner(mock_agent, progress_ledger=None)
        assert isinstance(runner.progress_ledger, NoOpProgressLedger)

    @pytest.mark.asyncio
    async def test_constructor_accepts_none_for_boundary(self, mock_agent):
        """Constructor should accept None for boundary (defaults to NoOpBoundary)."""
        runner = AgentRunner(mock_agent, boundary=None)
        assert isinstance(runner.boundary, NoOpBoundary)

    @pytest.mark.asyncio
    async def test_constructor_accepts_none_for_stall_detector(self, mock_agent):
        """Constructor should accept None for stall_detector (defaults to NoOpStallDetector)."""
        runner = AgentRunner(mock_agent, stall_detector=None)
        assert isinstance(runner.stall_detector, NoOpStallDetector)


class TestPerformance:
    """Test performance requirements."""

    def test_state_check_overhead_under_1ms(self, runner):
        """State check (10000 iterations) should take < 10ms (< 1ms average)."""
        iterations = 10000
        start = time.perf_counter_ns()

        for _ in range(iterations):
            _ = runner.state == AgentState.RUNNING

        end = time.perf_counter_ns()
        elapsed_ms = (end - start) / 1_000_000

        # 10000 iterations in < 10ms = < 1ms average per check
        assert elapsed_ms < 10, f"State check took {elapsed_ms:.2f}ms for {iterations} iterations"

    @pytest.mark.asyncio
    async def test_transition_overhead_under_1ms(self, runner):
        """transition() without logging should take < 1ms."""
        await runner.start()  # Setup

        # Measure transition time (pause to running)
        start = time.perf_counter_ns()
        await runner.pause()
        end = time.perf_counter_ns()

        elapsed_ms = (end - start) / 1_000_000

        # Allow some overhead for async/logging but should be fast
        assert elapsed_ms < 1, f"Transition took {elapsed_ms:.2f}ms"


class TestCleanup:
    """Test cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_is_idempotent(self, runner):
        """cleanup() should be idempotent (can be called multiple times)."""
        await runner.start()
        await runner.cancel()  # First cleanup via cancel

        # Call cleanup again
        await runner.cleanup()
        await runner.cleanup()

        # Should not raise error
        assert runner._cleaned_up is True
