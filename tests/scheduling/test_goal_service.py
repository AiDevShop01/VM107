"""
Tests for GoalService lifecycle management.

Tests:
- Governance enforcement (cannot create execution goal as agent)
- Auto-approve shortcut (maintenance goal → directly active)
- Activation triggers decomposition and task creation
- Invalid DAG prevents activation
- Task completion unblocks downstream tasks
- Goal auto-completes when all tasks terminal
- Pause/resume correctly stops/restarts task processing
"""

import pytest
from unittest.mock import Mock, MagicMock, call
from datetime import datetime, timezone

from core.scheduling.goal_service import GoalService, GoalServiceError
from core.scheduling.models import GoalModel, GoalCreateRequest, TaskModel
from core.scheduling.enums import GoalStatus, TaskStatus, GoalType, Priority
from core.scheduling.governance import GovernanceMatrix
from core.decomposition.engine import DecompositionEngine
from core.scheduling.dag import DAGValidator
from core.persistence.mongo_cache import MongoCachedCollection
from core.persistence.bulk_writer import TieredBulkWriter
from core.persistence.redis_queue import RedisPriorityQueue


@pytest.fixture
def mock_goal_cache():
    """Mock MongoCachedCollection for goals."""
    cache = Mock(spec=MongoCachedCollection)
    cache.get = Mock(return_value=None)
    return cache


@pytest.fixture
def mock_task_cache():
    """Mock MongoCachedCollection for tasks."""
    cache = Mock(spec=MongoCachedCollection)
    cache.get = Mock(return_value=None)
    return cache


@pytest.fixture
def mock_bulk_writer():
    """Mock TieredBulkWriter."""
    writer = Mock(spec=TieredBulkWriter)
    writer.write_critical = Mock()
    return writer


@pytest.fixture
def mock_decomposition_engine():
    """Mock DecompositionEngine."""
    engine = Mock(spec=DecompositionEngine)
    engine.decompose = Mock(return_value=[
        {
            "task_id": "task1",
            "goal_id": "goal1",
            "task_type": "analysis",
            "status": "pending",
            "priority": "P2",
            "dependencies": [],
            "blocked_by": []
        },
        {
            "task_id": "task2",
            "goal_id": "goal1",
            "task_type": "execution",
            "status": "pending",
            "priority": "P2",
            "dependencies": ["task1"],
            "blocked_by": ["task1"]
        }
    ])
    return engine


@pytest.fixture
def mock_governance():
    """Mock GovernanceMatrix."""
    return GovernanceMatrix()  # Use real governance for rules


@pytest.fixture
def mock_dag_validator():
    """Mock DAGValidator."""
    validator = Mock(spec=DAGValidator)
    validator.validate_and_order = Mock(return_value=["task1", "task2"])
    validator.find_runnable_tasks = Mock(return_value=["task1"])
    return validator


@pytest.fixture
def mock_queue():
    """Mock RedisPriorityQueue."""
    queue = Mock(spec=RedisPriorityQueue)
    queue.enqueue = Mock()
    queue.remove = Mock()
    return queue


@pytest.fixture
def goal_service(
    mock_goal_cache,
    mock_task_cache,
    mock_bulk_writer,
    mock_decomposition_engine,
    mock_governance,
    mock_dag_validator,
    mock_queue
):
    """Create GoalService with mocks."""
    return GoalService(
        goal_cache=mock_goal_cache,
        task_cache=mock_task_cache,
        bulk_writer=mock_bulk_writer,
        decomposition_engine=mock_decomposition_engine,
        governance=mock_governance,
        dag_validator=mock_dag_validator,
        queue=mock_queue
    )


def test_cannot_create_execution_goal_as_agent(goal_service):
    """Test governance prevents agent from creating execution goal."""
    request = GoalCreateRequest(
        title="Execute trade",
        description="Execute a live trade",
        goal_type=GoalType.EXECUTION,
        priority=Priority.P1,
        created_by="agent_001"
    )

    with pytest.raises(GoalServiceError) as exc_info:
        goal_service.create_goal(request, creator="agent_001")

    assert "cannot create" in str(exc_info.value).lower()


def test_maintenance_goal_auto_approved_to_active(goal_service, mock_bulk_writer):
    """Test maintenance goal goes directly to active status."""
    request = GoalCreateRequest(
        title="Data cleanup",
        description="Clean up old data",
        goal_type=GoalType.MAINTENANCE,
        priority=Priority.P3,
        created_by="agent_001",
        decomposition_template="cleanup_template"
    )

    goal = goal_service.create_goal(request, creator="agent_001")

    assert goal.status == GoalStatus.ACTIVE
    assert goal.goal_type == GoalType.MAINTENANCE
    assert goal.governance_tier == "auto"

    # Should write critical state
    mock_bulk_writer.write_critical.assert_called_once()


def test_research_goal_requires_approval(goal_service, mock_bulk_writer):
    """Test research goal goes to proposed status."""
    request = GoalCreateRequest(
        title="Research new strategy",
        description="Explore momentum strategy",
        goal_type=GoalType.RESEARCH,
        priority=Priority.P3,
        created_by="agent_001"
    )

    goal = goal_service.create_goal(request, creator="agent_001")

    assert goal.status == GoalStatus.PROPOSED
    assert goal.governance_tier == "approval"


def test_activation_triggers_decomposition_and_task_creation(
    goal_service, mock_goal_cache, mock_decomposition_engine, mock_bulk_writer, mock_queue
):
    """Test goal activation triggers decomposition and creates tasks."""
    # Mock existing goal (approved, ready for activation)
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "approved",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    # Activate
    goal = goal_service.activate_goal("goal1")

    # Should call decompose
    mock_decomposition_engine.decompose.assert_called_once()

    # Should create 2 tasks (from mock return value)
    assert mock_bulk_writer.write_critical.call_count == 3  # 2 tasks + 1 goal update

    # Should queue runnable task (task1 has no deps)
    mock_queue.enqueue.assert_called_once_with("task1", 5.0)


def test_invalid_dag_prevents_activation(
    goal_service, mock_goal_cache, mock_dag_validator
):
    """Test invalid DAG prevents goal activation."""
    # Mock existing goal (approved, ready for activation)
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "approved",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    # Mock DAG validator to raise error
    mock_dag_validator.validate_and_order.side_effect = ValueError("Circular dependency")

    with pytest.raises(GoalServiceError) as exc_info:
        goal_service.activate_goal("goal1")

    assert "Invalid DAG" in str(exc_info.value)


def test_task_completion_unblocks_downstream_tasks(
    goal_service, mock_goal_cache, mock_task_cache, mock_bulk_writer, mock_queue
):
    """Test task completion unblocks tasks that depend on it."""
    # Mock goal
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "active",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": ["task1", "task2"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    # Mock completed task
    def get_task(task_id):
        if task_id == "task1":
            return {
                "task_id": "task1",
                "goal_id": "goal1",
                "status": "completed"
            }
        elif task_id == "task2":
            return {
                "task_id": "task2",
                "goal_id": "goal1",
                "status": "blocked",
                "blocked_by": ["task1"]
            }
        return None

    mock_task_cache.get.side_effect = get_task

    # Complete task1
    goal_service.on_task_completed("task1")

    # Should unblock task2 (transition to queued)
    critical_writes = [call[0] for call in mock_bulk_writer.write_critical.call_args_list]
    task2_writes = [w for w in critical_writes if w[0] == "task2"]
    assert len(task2_writes) > 0
    assert task2_writes[0][1]["status"] == TaskStatus.QUEUED.value

    # Should enqueue task2
    mock_queue.enqueue.assert_called_with("task2", 5.0)


def test_goal_auto_completes_when_all_tasks_terminal(
    goal_service, mock_goal_cache, mock_task_cache, mock_bulk_writer
):
    """Test goal auto-completes when all tasks are terminal."""
    # Mock goal
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "active",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": ["task1", "task2"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    # Mock both tasks completed
    def get_task(task_id):
        return {
            "task_id": task_id,
            "goal_id": "goal1",
            "status": "completed"
        }

    mock_task_cache.get.side_effect = get_task

    # Complete last task
    goal_service.on_task_completed("task2")

    # Should mark goal as completed
    critical_writes = [call[0] for call in mock_bulk_writer.write_critical.call_args_list]
    goal_writes = [w for w in critical_writes if w[0] == "goal1"]
    assert len(goal_writes) > 0
    assert goal_writes[0][1]["status"] == GoalStatus.COMPLETED.value


def test_pause_goal_stops_task_processing(
    goal_service, mock_goal_cache, mock_task_cache, mock_bulk_writer, mock_queue
):
    """Test pause transitions tasks to pending and removes from queue."""
    # Mock active goal
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "active",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": ["task1", "task2"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    # Mock tasks: task1 running, task2 queued
    def get_task(task_id):
        if task_id == "task1":
            return {"task_id": "task1", "goal_id": "goal1", "status": "running"}
        elif task_id == "task2":
            return {"task_id": "task2", "goal_id": "goal1", "status": "queued"}
        return None

    mock_task_cache.get.side_effect = get_task

    # Pause
    goal = goal_service.pause_goal("goal1")

    assert goal.status == GoalStatus.PAUSED

    # Should transition both tasks to pending
    critical_writes = [call[0] for call in mock_bulk_writer.write_critical.call_args_list]
    task_writes = [w for w in critical_writes if w[0] in ["task1", "task2"]]
    assert len(task_writes) == 2

    # Should remove from queue
    assert mock_queue.remove.call_count == 2


def test_resume_goal_restarts_task_processing(
    goal_service, mock_goal_cache, mock_task_cache, mock_bulk_writer, mock_queue
):
    """Test resume transitions tasks to queued and re-enqueues."""
    # Mock paused goal
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "paused",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": ["task1", "task2"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    # Mock both tasks pending
    def get_task(task_id):
        return {"task_id": task_id, "goal_id": "goal1", "status": "pending"}

    mock_task_cache.get.side_effect = get_task

    # Resume
    goal = goal_service.resume_goal("goal1")

    assert goal.status == GoalStatus.ACTIVE

    # Should transition tasks to queued
    critical_writes = [call[0] for call in mock_bulk_writer.write_critical.call_args_list]
    task_writes = [w for w in critical_writes if w[0] in ["task1", "task2"]]
    assert len(task_writes) == 2

    # Should re-enqueue
    assert mock_queue.enqueue.call_count == 2


def test_propose_goal_invalid_transition_raises_error(goal_service, mock_goal_cache):
    """Test proposing non-draft goal raises error."""
    mock_goal_cache.get.return_value = {
        "goal_id": "goal1",
        "title": "Test goal",
        "description": "Test",
        "goal_type": "maintenance",
        "status": "active",
        "priority": "P2",
        "created_by": "agent_001",
        "governance_tier": "auto",
        "decomposition_template": "test_template",
        "task_ids": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "schema_version": 1
    }

    with pytest.raises(GoalServiceError) as exc_info:
        goal_service.propose_goal("goal1")

    assert "Cannot propose goal" in str(exc_info.value)
