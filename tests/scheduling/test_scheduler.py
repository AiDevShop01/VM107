"""
Tests for Scheduler orchestrator.

Tests:
- Brain update respects cadence guard
- Batch selection respects max_concurrent_tasks
- Task transitions to running with critical write
- Degraded mode activates on Redis failure
- Degraded mode restores after N healthy checks
- Pre-emption check runs when conditions met
- Reconciliation runs on interval
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, call

from core.scheduling.scheduler import Scheduler
from core.scheduling.brain import BrainLayer, SchedulerControl
from core.scheduling.scoring import TaskScorer
from core.scheduling.preemption import PreemptionManager, PreemptionResult
from core.scheduling.dag import DAGValidator
from core.persistence.redis_queue import RedisPriorityQueue, SchedulerDegradedError
from core.persistence.mongo_cache import MongoCachedCollection
from core.persistence.bulk_writer import TieredBulkWriter
from core.persistence.reconciliation import ReconciliationJob, ReconciliationResult
from core.scheduling.enums import BehavioralMode, ResourcePolicy, Priority, TaskStatus


@pytest.fixture
def mock_brain():
    """Mock BrainLayer."""
    brain = Mock(spec=BrainLayer)
    brain.update_cycle = Mock()
    brain.get_scheduler_control = Mock(return_value=SchedulerControl(
        max_concurrent_tasks=5,
        max_cost_per_cycle=10.0,
        max_tokens_per_cycle=100000,
        blocked_goal_ids=[],
        priority_weights={"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
        goal_priority_overrides={},
        expansion_policy="enabled",
        preemption_enabled=False,
        preemption_threshold=2.0,
        max_preemptions_per_cycle=1,
        aging_enabled=True,
        aging_factor=1.0
    ))
    brain.get_brain_context = Mock(return_value={
        "mode": "exploration",
        "confidence_global": 0.7,
        "resource_policy": "normal"
    })
    return brain


@pytest.fixture
def mock_scorer():
    """Mock TaskScorer."""
    scorer = Mock(spec=TaskScorer)
    scorer.score_batch = Mock(return_value=[
        ("task1", 10.0),
        ("task2", 8.0),
        ("task3", 6.0)
    ])
    return scorer


@pytest.fixture
def mock_queue():
    """Mock RedisPriorityQueue."""
    queue = Mock(spec=RedisPriorityQueue)
    queue.dequeue_batch = Mock(return_value=[
        ("task1", 10.0),
        ("task2", 8.0)
    ])
    queue.update_score = Mock()
    queue.peek_top = Mock(return_value=[])
    return queue


@pytest.fixture
def mock_preemption_mgr():
    """Mock PreemptionManager."""
    mgr = Mock(spec=PreemptionManager)
    mgr.reset_cycle = Mock()
    mgr.check_preemption = Mock(return_value=PreemptionResult(
        should_preempt=False,
        target_task_id=None,
        reason="No pre-emption needed"
    ))
    return mgr


@pytest.fixture
def mock_task_cache():
    """Mock MongoCachedCollection for tasks."""
    cache = Mock(spec=MongoCachedCollection)
    cache.get = Mock(side_effect=lambda task_id: {
        "task_id": task_id,
        "goal_id": "goal1",
        "status": "queued",
        "priority": Priority.P2
    })
    return cache


@pytest.fixture
def mock_goal_cache():
    """Mock MongoCachedCollection for goals."""
    cache = Mock(spec=MongoCachedCollection)
    cache.get = Mock(return_value={
        "goal_id": "goal1",
        "success_rate": 0.8
    })
    return cache


@pytest.fixture
def mock_bulk_writer():
    """Mock TieredBulkWriter."""
    writer = Mock(spec=TieredBulkWriter)
    writer.write_critical = Mock()
    writer.write_important = Mock()
    writer.flush_all = Mock()
    return writer


@pytest.fixture
def mock_reconciliation():
    """Mock ReconciliationJob."""
    job = Mock(spec=ReconciliationJob)
    job.run = Mock(return_value=ReconciliationResult(
        healed_tasks=2,
        removed_stale=1,
        brain_state_healed=False,
        duration_ms=50
    ))
    return job


@pytest.fixture
def mock_dag_validator():
    """Mock DAGValidator."""
    return Mock(spec=DAGValidator)


@pytest.fixture
def mock_worker_callback():
    """Mock worker callback function."""
    return Mock()


@pytest.fixture
def scheduler(
    mock_brain,
    mock_scorer,
    mock_queue,
    mock_preemption_mgr,
    mock_task_cache,
    mock_goal_cache,
    mock_bulk_writer,
    mock_reconciliation,
    mock_dag_validator,
    mock_worker_callback
):
    """Create Scheduler instance with all mocks."""
    return Scheduler(
        brain=mock_brain,
        scorer=mock_scorer,
        queue=mock_queue,
        preemption_mgr=mock_preemption_mgr,
        task_cache=mock_task_cache,
        goal_cache=mock_goal_cache,
        bulk_writer=mock_bulk_writer,
        reconciliation=mock_reconciliation,
        dag_validator=mock_dag_validator,
        max_workers=5,
        worker_callback=mock_worker_callback,
        loop_interval_seconds=5.0,
        brain_cadence_seconds=5.0,
        reconciliation_interval_seconds=60.0,
        batch_size=5
    )


def test_brain_update_respects_cadence_guard(scheduler, mock_brain):
    """Test brain update only runs when cadence guard allows."""
    # First cycle - should update
    scheduler.run_cycle()
    assert mock_brain.update_cycle.call_count == 1

    # Second cycle immediately - should NOT update (cadence not elapsed)
    scheduler.run_cycle()
    assert mock_brain.update_cycle.call_count == 1  # Still 1

    # Wait for cadence, then run - should update
    scheduler._last_brain_update = time.time() - 10.0  # Simulate 10s elapsed
    scheduler.run_cycle()
    assert mock_brain.update_cycle.call_count == 2


def test_batch_selection_respects_max_concurrent_tasks(scheduler, mock_queue):
    """Test batch dequeue respects max_concurrent_tasks from scheduler_control."""
    # Add 3 running tasks
    scheduler._running_tasks = {
        "running1": {"task_id": "running1"},
        "running2": {"task_id": "running2"},
        "running3": {"task_id": "running3"}
    }

    # Max is 5, running is 3, so should dequeue min(5-3, batch_size=5) = 2
    scheduler.run_cycle()

    # Check dequeue_batch was called with correct count
    mock_queue.dequeue_batch.assert_called_once_with(2)


def test_dequeued_tasks_transition_to_running_with_critical_write(
    scheduler, mock_bulk_writer, mock_worker_callback
):
    """Test dequeued tasks transition to running with critical write."""
    scheduler.run_cycle()

    # Should write critical state change for both dequeued tasks
    assert mock_bulk_writer.write_critical.call_count == 2

    # Check status was set to RUNNING
    calls = mock_bulk_writer.write_critical.call_args_list
    assert calls[0][0][1]["status"] == TaskStatus.RUNNING.value
    assert calls[1][0][1]["status"] == TaskStatus.RUNNING.value

    # Should dispatch both tasks
    assert mock_worker_callback.call_count == 2


def test_degraded_mode_activates_on_redis_failure(scheduler, mock_queue):
    """Test scheduler enters degraded mode when Redis fails."""
    # Mock Redis failure
    mock_queue.update_score.side_effect = SchedulerDegradedError("Redis unavailable")

    # Mock some tasks to trigger update_score
    scheduler._fetch_runnable_tasks = Mock(return_value=[
        {"task_id": "task1", "goal_id": "goal1", "priority": Priority.P2}
    ])
    scheduler._score_tasks = Mock(return_value=[("task1", 10.0)])

    # Run cycle - should enter degraded mode
    scheduler.run_cycle()

    assert scheduler._degraded_mode is True
    assert scheduler.max_workers == 2
    assert scheduler.loop_interval_seconds == 10.0


def test_degraded_mode_restores_after_n_consecutive_healthy_checks(scheduler):
    """Test degraded mode restores after 3 consecutive healthy cycles."""
    # Enter degraded mode
    scheduler._degraded_mode = True
    scheduler.max_workers = 2
    scheduler.loop_interval_seconds = 10.0
    scheduler._consecutive_healthy_checks = 0

    # Run 2 healthy cycles - should not restore
    scheduler.run_cycle()
    assert scheduler._degraded_mode is True
    assert scheduler._consecutive_healthy_checks == 1

    scheduler.run_cycle()
    assert scheduler._degraded_mode is True
    assert scheduler._consecutive_healthy_checks == 2

    # Run 3rd healthy cycle - should restore
    scheduler.run_cycle()
    assert scheduler._degraded_mode is False
    assert scheduler.max_workers == 5
    assert scheduler.loop_interval_seconds == 5.0


def test_preemption_check_runs_when_no_free_workers(
    scheduler, mock_queue, mock_preemption_mgr, mock_brain
):
    """Test pre-emption check runs when P1 available and no free workers."""
    # Enable pre-emption
    mock_brain.get_scheduler_control.return_value = SchedulerControl(
        max_concurrent_tasks=5,
        max_cost_per_cycle=10.0,
        max_tokens_per_cycle=100000,
        blocked_goal_ids=[],
        priority_weights={"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5},
        goal_priority_overrides={},
        expansion_policy="enabled",
        preemption_enabled=True,
        preemption_threshold=2.0,
        max_preemptions_per_cycle=1,
        aging_enabled=True,
        aging_factor=1.0
    )

    # Fill workers (max_concurrent_tasks = 5)
    scheduler._running_tasks = {
        f"task{i}": {"task_id": f"task{i}"} for i in range(5)
    }

    # Mock P1 task in queue
    mock_queue.peek_top.return_value = [("p1_task", 15.0)]

    # Run cycle
    scheduler.run_cycle()

    # Should call check_preemption
    assert mock_preemption_mgr.check_preemption.call_count == 1


def test_reconciliation_runs_on_interval(scheduler, mock_reconciliation):
    """Test reconciliation runs every reconciliation_interval seconds."""
    # First cycle - should run (initial run)
    scheduler.run_cycle()
    assert mock_reconciliation.run.call_count == 1

    # Second cycle immediately - should NOT run
    scheduler.run_cycle()
    assert mock_reconciliation.run.call_count == 1

    # Simulate interval elapsed
    scheduler._last_reconciliation = time.time() - 70.0  # 70s elapsed
    scheduler.run_cycle()
    assert mock_reconciliation.run.call_count == 2


def test_preemption_manager_reset_at_cycle_start(scheduler, mock_preemption_mgr):
    """Test pre-emption manager is reset at start of each cycle."""
    scheduler.run_cycle()
    mock_preemption_mgr.reset_cycle.assert_called_once()

    scheduler.run_cycle()
    assert mock_preemption_mgr.reset_cycle.call_count == 2


def test_bulk_writer_flush_at_cycle_end(scheduler, mock_bulk_writer):
    """Test bulk writer flushes at end of each cycle."""
    scheduler.run_cycle()
    mock_bulk_writer.flush_all.assert_called_once()

    scheduler.run_cycle()
    assert mock_bulk_writer.flush_all.call_count == 2


def test_task_dispatch_includes_brain_context(
    scheduler, mock_worker_callback, mock_brain
):
    """Test dispatched tasks include brain context in envelope."""
    scheduler.run_cycle()

    # Check worker callback was called with envelope containing brain_context
    assert mock_worker_callback.call_count == 2
    envelope = mock_worker_callback.call_args_list[0][0][1]

    assert "brain_context" in envelope
    assert envelope["brain_context"]["mode"] == "exploration"
    assert envelope["brain_context"]["confidence_global"] == 0.7
    assert envelope["brain_context"]["resource_policy"] == "normal"


def test_task_completed_removes_from_running_set(scheduler):
    """Test task_completed removes task from running set."""
    scheduler._running_tasks = {
        "task1": {"task_id": "task1"},
        "task2": {"task_id": "task2"}
    }

    scheduler.task_completed("task1")

    assert "task1" not in scheduler._running_tasks
    assert "task2" in scheduler._running_tasks
    assert len(scheduler._running_tasks) == 1
