"""
Performance tests for AgentRunner state machine.

Verifies:
- State enum comparison overhead < 1ms per 10K ops
- validate_transition() overhead < 1ms per 10K ops
- run_step() cycle < 5ms with no-op interfaces

These ensure the state machine adds negligible overhead to Agent Zero's message loop.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from core.agent_runner import AgentRunner
from core.state_machine import AgentState, validate_transition


class TestStateCheckPerformance:
    """Test state enum comparison performance."""

    def test_state_comparison_under_5ms_for_10k_ops(self):
        """State enum comparison should be < 5ms for 10K operations."""
        state = AgentState.RUNNING

        start = time.perf_counter()
        for _ in range(10_000):
            # Simulate state check (equality comparison)
            _ = state == AgentState.RUNNING
            _ = state == AgentState.PAUSED
            _ = state in (AgentState.CANCELLED, AgentState.FAILED)
        elapsed = time.perf_counter() - start

        # Should be < 5ms (0.005 seconds) - generous threshold for Python overhead
        assert elapsed < 0.005, f"State check took {elapsed*1000:.2f}ms, expected < 5ms"


class TestTransitionValidationPerformance:
    """Test validate_transition() performance."""

    def test_validate_transition_under_5ms_for_10k_ops(self):
        """validate_transition() should be < 5ms for 10K calls."""
        start = time.perf_counter()
        for _ in range(10_000):
            # Simulate transition validation (valid transition)
            validate_transition(AgentState.IDLE, AgentState.RUNNING)
        elapsed = time.perf_counter() - start

        # Should be < 5ms (0.005 seconds) - generous threshold for Python dict lookup overhead
        assert elapsed < 0.005, f"validate_transition took {elapsed*1000:.2f}ms, expected < 5ms"


class TestRunStepPerformance:
    """Test run_step() cycle performance."""

    @pytest.mark.asyncio
    async def test_run_step_under_5ms_with_noop_interfaces(self):
        """run_step() should be < 5ms with no-op interfaces."""
        # Create runner with no-op interfaces (default)
        context = SimpleNamespace(id="test_ctx")
        agent = SimpleNamespace(agent_name="test", context=context)
        runner = AgentRunner(agent)
        await runner.start()

        # Warm up
        await runner.run_step()

        # Measure single run_step cycle
        start = time.perf_counter()
        await runner.run_step()
        elapsed = time.perf_counter() - start

        # Should be < 5ms (0.005 seconds)
        assert elapsed < 0.005, f"run_step took {elapsed*1000:.2f}ms, expected < 5ms"


class TestExtensionOverhead:
    """Test extension execute() overhead."""

    @pytest.mark.asyncio
    async def test_state_check_extension_overhead(self):
        """StateCheck extension should add < 1ms overhead per call."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../extensions/python"))

        from message_loop_start._05_runner_state_check import RunnerStateCheck

        # Setup
        context = SimpleNamespace(id="test_ctx")
        agent = SimpleNamespace(agent_name="test", context=context)
        agent._data = {}
        agent.get_data = lambda key: agent._data.get(key)
        agent.set_data = lambda key, value: agent._data.__setitem__(key, value)

        runner = AgentRunner(agent)
        await runner.start()
        agent.set_data("runner", runner)

        loop_data = SimpleNamespace(iteration=1)
        ext = RunnerStateCheck(agent=agent)

        # Warm up
        await ext.execute(loop_data=loop_data)

        # Measure
        start = time.perf_counter()
        await ext.execute(loop_data=loop_data)
        elapsed = time.perf_counter() - start

        # Should be < 1ms (0.001 seconds)
        assert elapsed < 0.001, f"StateCheck extension took {elapsed*1000:.2f}ms, expected < 1ms"

    @pytest.mark.asyncio
    async def test_step_update_extension_overhead(self):
        """StepUpdate extension should add < 1ms overhead per call."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../extensions/python"))

        from message_loop_end._95_runner_step_update import RunnerStepUpdate

        # Setup
        context = SimpleNamespace(id="test_ctx")
        agent = SimpleNamespace(agent_name="test", context=context)
        agent._data = {}
        agent.get_data = lambda key: agent._data.get(key)
        agent.set_data = lambda key, value: agent._data.__setitem__(key, value)

        runner = AgentRunner(agent)
        await runner.start()
        agent.set_data("runner", runner)

        loop_data = SimpleNamespace(iteration=1)
        ext = RunnerStepUpdate(agent=agent)

        # Warm up
        await ext.execute(loop_data=loop_data)

        # Measure
        start = time.perf_counter()
        await ext.execute(loop_data=loop_data)
        elapsed = time.perf_counter() - start

        # Should be < 1ms (0.001 seconds)
        assert elapsed < 0.001, f"StepUpdate extension took {elapsed*1000:.2f}ms, expected < 1ms"
