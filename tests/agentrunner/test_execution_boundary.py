"""
Tests for ExecutionBoundary and expanded BoundaryStatus.

Tests boundary enforcement with all 5 limits and expanded status values.
"""
import time
from unittest.mock import Mock

import pytest

from core.execution_context import BoundaryStatus, ExecutionContext
from core.boundary import (
    ResolvedBoundaryConfig,
    InMemoryBudgetTracker,
)
from core.boundary.execution_boundary import ExecutionBoundary
from core.interfaces.boundary import ExecutionBoundaryInterface


# ===== BoundaryStatus Expansion Tests =====

def test_backward_compat_ok():
    """BoundaryStatus.OK still works with value 'ok'."""
    assert BoundaryStatus.OK.value == "ok"


def test_backward_compat_warning():
    """BoundaryStatus.WARNING still works with value 'warning'."""
    assert BoundaryStatus.WARNING.value == "warning"


def test_backward_compat_exceeded():
    """BoundaryStatus.EXCEEDED still works with value 'exceeded'."""
    assert BoundaryStatus.EXCEEDED.value == "exceeded"


def test_new_status_values():
    """All 5 new EXCEEDED types exist with correct string values."""
    assert BoundaryStatus.STEP_LIMIT_EXCEEDED.value == "step_limit_exceeded"
    assert BoundaryStatus.TOKEN_LIMIT_EXCEEDED.value == "token_limit_exceeded"
    assert BoundaryStatus.COST_LIMIT_EXCEEDED.value == "cost_limit_exceeded"
    assert BoundaryStatus.TIME_LIMIT_EXCEEDED.value == "time_limit_exceeded"
    assert BoundaryStatus.DAILY_BUDGET_EXCEEDED.value == "daily_budget_exceeded"


def test_is_exceeded_helper():
    """Helper method distinguishes OK/WARNING from all EXCEEDED types."""
    # OK and WARNING should return False
    assert BoundaryStatus.OK.is_exceeded() is False
    assert BoundaryStatus.WARNING.is_exceeded() is False

    # All EXCEEDED variants should return True
    assert BoundaryStatus.EXCEEDED.is_exceeded() is True
    assert BoundaryStatus.STEP_LIMIT_EXCEEDED.is_exceeded() is True
    assert BoundaryStatus.TOKEN_LIMIT_EXCEEDED.is_exceeded() is True
    assert BoundaryStatus.COST_LIMIT_EXCEEDED.is_exceeded() is True
    assert BoundaryStatus.TIME_LIMIT_EXCEEDED.is_exceeded() is True
    assert BoundaryStatus.DAILY_BUDGET_EXCEEDED.is_exceeded() is True


# ===== ExecutionBoundary Tests =====

@pytest.fixture
def minimal_config():
    """Minimal boundary config for testing."""
    return ResolvedBoundaryConfig(
        max_steps=10,
        max_tokens=1000,
        max_cost_usd=1.0,
        max_execution_time_sec=60,
        daily_budget_usd=10.0,
    )


@pytest.fixture
def budget_tracker():
    """In-memory budget tracker for testing."""
    return InMemoryBudgetTracker()


@pytest.fixture
def execution_boundary(minimal_config, budget_tracker):
    """ExecutionBoundary instance for testing."""
    return ExecutionBoundary(
        config=minimal_config,
        budget_tracker=budget_tracker,
        agent_name="test_agent",
    )


@pytest.mark.asyncio
async def test_all_within_limits(execution_boundary):
    """Returns OK when all metrics below thresholds."""
    context = ExecutionContext(
        task_id="task1",
        step_count=5,
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 30,  # 30 seconds ago
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.OK


@pytest.mark.asyncio
async def test_step_limit_exceeded(execution_boundary):
    """Returns STEP_LIMIT_EXCEEDED when step_count >= max_steps."""
    context = ExecutionContext(
        task_id="task1",
        step_count=10,  # At limit
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 30,
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.STEP_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_token_limit_exceeded(execution_boundary):
    """Returns TOKEN_LIMIT_EXCEEDED when token_count >= max_tokens."""
    context = ExecutionContext(
        task_id="task1",
        step_count=5,
        token_count=1000,  # At limit
        cost_usd=0.5,
        start_time=time.time() - 30,
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.TOKEN_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_cost_limit_exceeded(execution_boundary):
    """Returns COST_LIMIT_EXCEEDED when cost_usd >= max_cost_usd."""
    context = ExecutionContext(
        task_id="task1",
        step_count=5,
        token_count=500,
        cost_usd=1.0,  # At limit
        start_time=time.time() - 30,
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.COST_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_time_limit_exceeded(execution_boundary):
    """Returns TIME_LIMIT_EXCEEDED when elapsed >= max_execution_time_sec."""
    context = ExecutionContext(
        task_id="task1",
        step_count=5,
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 60,  # 60 seconds ago (at limit)
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.TIME_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_daily_budget_exceeded(execution_boundary, budget_tracker):
    """Returns DAILY_BUDGET_EXCEEDED when daily_total >= daily_budget_usd."""
    # Add spend to exceed daily budget
    budget_tracker.add_spend("test_agent", 5.0)
    budget_tracker.add_spend("other_agent", 5.0)  # Total = 10.0

    context = ExecutionContext(
        task_id="task1",
        step_count=5,
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 30,
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.DAILY_BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_warning_at_80_percent(execution_boundary):
    """Returns WARNING when any metric at 80% threshold."""
    # Test step warning (8 steps = 80% of 10)
    context = ExecutionContext(
        task_id="task1",
        step_count=8,
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 30,
    )

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.WARNING


@pytest.mark.asyncio
async def test_warning_logged_once(execution_boundary, caplog):
    """Same warning not logged twice for same limit."""
    context = ExecutionContext(
        task_id="task1",
        step_count=8,  # 80% of limit
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 30,
    )

    # First check - should log warning
    await execution_boundary.check(context)
    warning_count_1 = len([r for r in caplog.records if "80%" in r.message])

    # Second check - should NOT log again
    await execution_boundary.check(context)
    warning_count_2 = len([r for r in caplog.records if "80%" in r.message])

    assert warning_count_2 == warning_count_1  # No new warnings


@pytest.mark.asyncio
async def test_violation_structured_log(execution_boundary, caplog):
    """Violation produces correct JSON structure."""
    context = ExecutionContext(
        task_id="task1",
        step_count=10,  # Exceeded
        token_count=500,
        cost_usd=0.5,
        start_time=time.time() - 30,
    )

    await execution_boundary.check(context)

    # Should have logged violation
    violations = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(violations) > 0

    # Log message should be JSON (contains violation_type)
    assert "violation_type" in violations[0].message or "step_limit_exceeded" in violations[0].message


@pytest.mark.asyncio
async def test_check_priority(execution_boundary):
    """Step checked first, then token, then cost, then time, then daily budget."""
    # Set ALL limits exceeded - should return STEP_LIMIT_EXCEEDED first
    context = ExecutionContext(
        task_id="task1",
        step_count=10,  # Step exceeded
        token_count=1000,  # Token exceeded
        cost_usd=1.0,  # Cost exceeded
        start_time=time.time() - 60,  # Time exceeded
    )
    execution_boundary._budget_tracker.add_spend("test_agent", 10.0)  # Daily budget exceeded

    status = await execution_boundary.check(context)
    assert status == BoundaryStatus.STEP_LIMIT_EXCEEDED  # Returns first violation


@pytest.mark.asyncio
async def test_check_performance():
    """10000 boundary checks complete in < 10ms total (< 1ms per check)."""
    config = ResolvedBoundaryConfig(
        max_steps=100,
        max_tokens=10000,
        max_cost_usd=10.0,
        max_execution_time_sec=600,
        daily_budget_usd=100.0,
    )
    tracker = InMemoryBudgetTracker()
    boundary = ExecutionBoundary(config=config, budget_tracker=tracker, agent_name="perf_test")

    context = ExecutionContext(
        task_id="perf_task",
        step_count=50,
        token_count=5000,
        cost_usd=5.0,
        start_time=time.time() - 300,
    )

    start = time.perf_counter()
    for _ in range(10000):
        await boundary.check(context)
    elapsed = time.perf_counter() - start

    # < 1ms per check means 10,000 checks in < 10 seconds
    # But really we want < 0.1s for 10,000 checks (< 10 microseconds per check)
    assert elapsed < 0.1  # < 100ms total (plenty of margin)


def test_implements_protocol():
    """ExecutionBoundary satisfies ExecutionBoundaryInterface protocol."""
    config = ResolvedBoundaryConfig(
        max_steps=10,
        max_tokens=1000,
        max_cost_usd=1.0,
        max_execution_time_sec=60,
        daily_budget_usd=10.0,
    )
    tracker = InMemoryBudgetTracker()
    boundary = ExecutionBoundary(config=config, budget_tracker=tracker, agent_name="test")

    assert isinstance(boundary, ExecutionBoundaryInterface)
