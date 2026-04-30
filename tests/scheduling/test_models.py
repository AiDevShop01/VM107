"""Tests for Goal/Task models, enums, and governance."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from core.scheduling.enums import (
    GoalStatus,
    TaskStatus,
    GoalType,
    Priority,
    BehavioralMode,
    ResourcePolicy,
)
from core.scheduling.models import GoalModel, TaskModel, GoalCreateRequest, TaskCreateRequest
from core.scheduling.governance import GovernanceMatrix, GovernanceRule


# ============================================================================
# GoalStatus Enum Tests
# ============================================================================


class TestGoalStatus:
    """Test GoalStatus enum and lifecycle transitions."""

    def test_goal_status_has_8_states(self):
        """GoalStatus must have exactly 8 states."""
        assert len(GoalStatus) == 8
        assert GoalStatus.DRAFT.value == "draft"
        assert GoalStatus.PROPOSED.value == "proposed"
        assert GoalStatus.APPROVED.value == "approved"
        assert GoalStatus.ACTIVE.value == "active"
        assert GoalStatus.PAUSED.value == "paused"
        assert GoalStatus.COMPLETED.value == "completed"
        assert GoalStatus.FAILED.value == "failed"
        assert GoalStatus.CANCELLED.value == "cancelled"

    @pytest.mark.parametrize(
        "from_state,to_state,expected",
        [
            # Valid transitions
            (GoalStatus.DRAFT, GoalStatus.PROPOSED, True),
            (GoalStatus.PROPOSED, GoalStatus.APPROVED, True),
            (GoalStatus.APPROVED, GoalStatus.ACTIVE, True),
            (GoalStatus.ACTIVE, GoalStatus.PAUSED, True),
            (GoalStatus.ACTIVE, GoalStatus.COMPLETED, True),
            (GoalStatus.ACTIVE, GoalStatus.FAILED, True),
            (GoalStatus.ACTIVE, GoalStatus.CANCELLED, True),
            (GoalStatus.PAUSED, GoalStatus.ACTIVE, True),
            (GoalStatus.PAUSED, GoalStatus.CANCELLED, True),
            # Shortcuts for maintenance/learning
            (GoalStatus.DRAFT, GoalStatus.ACTIVE, True),
            # Invalid transitions
            (GoalStatus.DRAFT, GoalStatus.ACTIVE, True),  # Allowed as shortcut
            (GoalStatus.DRAFT, GoalStatus.COMPLETED, False),
            (GoalStatus.PROPOSED, GoalStatus.ACTIVE, False),
            (GoalStatus.COMPLETED, GoalStatus.ACTIVE, False),
            (GoalStatus.FAILED, GoalStatus.ACTIVE, False),
            (GoalStatus.CANCELLED, GoalStatus.ACTIVE, False),
        ],
    )
    def test_goal_status_transitions(self, from_state, to_state, expected):
        """Test GoalStatus transition validation."""
        assert GoalStatus.validate_transition(from_state, to_state) == expected


# ============================================================================
# TaskStatus Enum Tests
# ============================================================================


class TestTaskStatus:
    """Test TaskStatus enum and lifecycle transitions."""

    def test_task_status_has_7_states(self):
        """TaskStatus must have exactly 7 states."""
        assert len(TaskStatus) == 7
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.BLOCKED.value == "blocked"
        assert TaskStatus.QUEUED.value == "queued"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"

    @pytest.mark.parametrize(
        "from_state,to_state,expected",
        [
            # Valid transitions
            (TaskStatus.PENDING, TaskStatus.BLOCKED, True),
            (TaskStatus.PENDING, TaskStatus.QUEUED, True),
            (TaskStatus.BLOCKED, TaskStatus.QUEUED, True),
            (TaskStatus.QUEUED, TaskStatus.RUNNING, True),
            (TaskStatus.RUNNING, TaskStatus.COMPLETED, True),
            (TaskStatus.RUNNING, TaskStatus.FAILED, True),
            (TaskStatus.RUNNING, TaskStatus.CANCELLED, True),
            # Invalid transitions
            (TaskStatus.PENDING, TaskStatus.RUNNING, False),
            (TaskStatus.PENDING, TaskStatus.COMPLETED, False),
            (TaskStatus.COMPLETED, TaskStatus.RUNNING, False),
            (TaskStatus.FAILED, TaskStatus.RUNNING, False),
            (TaskStatus.CANCELLED, TaskStatus.RUNNING, False),
        ],
    )
    def test_task_status_transitions(self, from_state, to_state, expected):
        """Test TaskStatus transition validation."""
        assert TaskStatus.validate_transition(from_state, to_state) == expected


# ============================================================================
# Priority Enum Tests
# ============================================================================


class TestPriority:
    """Test Priority enum with base_weight property."""

    def test_priority_has_4_values(self):
        """Priority must have P1-P4."""
        assert len(Priority) == 4
        assert Priority.P1.value == "P1"
        assert Priority.P2.value == "P2"
        assert Priority.P3.value == "P3"
        assert Priority.P4.value == "P4"

    def test_priority_base_weight(self):
        """Priority must have correct base_weight values."""
        assert Priority.P1.base_weight == 4.0
        assert Priority.P2.base_weight == 2.0
        assert Priority.P3.base_weight == 1.0
        assert Priority.P4.base_weight == 0.5


# ============================================================================
# Other Enums Tests
# ============================================================================


class TestOtherEnums:
    """Test GoalType, BehavioralMode, and ResourcePolicy enums."""

    def test_goal_type_has_5_values(self):
        """GoalType must have 5 types."""
        assert len(GoalType) == 5
        assert GoalType.MAINTENANCE.value == "maintenance"
        assert GoalType.LEARNING.value == "learning"
        assert GoalType.RESEARCH.value == "research"
        assert GoalType.EXECUTION.value == "execution"
        assert GoalType.SYSTEM.value == "system"

    def test_behavioral_mode_has_3_values(self):
        """BehavioralMode must have 3 modes."""
        assert len(BehavioralMode) == 3
        assert BehavioralMode.EXPLORATION.value == "exploration"
        assert BehavioralMode.EXPLOITATION.value == "exploitation"
        assert BehavioralMode.STABILIZATION.value == "stabilization"

    def test_resource_policy_has_2_values(self):
        """ResourcePolicy must have 2 policies."""
        assert len(ResourcePolicy) == 2
        assert ResourcePolicy.NORMAL.value == "normal"
        assert ResourcePolicy.CONSTRAINED.value == "constrained"


# ============================================================================
# GoalModel Tests
# ============================================================================


class TestGoalModel:
    """Test GoalModel Pydantic validation."""

    def test_goal_model_valid_creation(self, valid_goal_data):
        """GoalModel can be created with valid data."""
        goal = GoalModel(**valid_goal_data)
        assert goal.goal_id == "goal-test-001"
        assert goal.title == "Test Goal"
        assert goal.goal_type == GoalType.MAINTENANCE
        assert goal.status == GoalStatus.DRAFT
        assert goal.priority == Priority.P2
        assert goal.schema_version == 1

    def test_goal_model_requires_fields(self, valid_goal_data):
        """GoalModel requires all mandatory fields."""
        for field in ["goal_id", "title", "description", "goal_type", "status", "priority", "created_by"]:
            data = valid_goal_data.copy()
            del data[field]
            with pytest.raises(ValidationError):
                GoalModel(**data)

    def test_goal_model_title_length_validation(self, valid_goal_data):
        """GoalModel title must be 3-200 chars."""
        # Too short
        data = valid_goal_data.copy()
        data["title"] = "ab"
        with pytest.raises(ValidationError):
            GoalModel(**data)

        # Too long
        data["title"] = "x" * 201
        with pytest.raises(ValidationError):
            GoalModel(**data)

        # Valid
        data["title"] = "abc"
        goal = GoalModel(**data)
        assert goal.title == "abc"

    def test_goal_model_optional_fields(self, valid_goal_data):
        """GoalModel accepts optional fields."""
        data = valid_goal_data.copy()
        data["objective_label"] = "market_intelligence"
        data["decomposition_template"] = "research_template"
        data["budget_max_cost_usd"] = 10.0
        data["budget_max_tokens"] = 100000
        data["task_ids"] = ["task-001", "task-002"]

        goal = GoalModel(**data)
        assert goal.objective_label == "market_intelligence"
        assert goal.decomposition_template == "research_template"
        assert goal.budget_max_cost_usd == 10.0
        assert goal.budget_max_tokens == 100000
        assert goal.task_ids == ["task-001", "task-002"]

    def test_goal_model_forbids_extra_fields(self, valid_goal_data):
        """GoalModel forbids extra fields."""
        data = valid_goal_data.copy()
        data["unknown_field"] = "should fail"
        with pytest.raises(ValidationError):
            GoalModel(**data)


# ============================================================================
# TaskModel Tests
# ============================================================================


class TestTaskModel:
    """Test TaskModel Pydantic validation."""

    def test_task_model_valid_creation(self, valid_task_data):
        """TaskModel can be created with valid data."""
        task = TaskModel(**valid_task_data)
        assert task.task_id == "task-test-001"
        assert task.goal_id == "goal-test-001"
        assert task.task_type == "analysis"
        assert task.status == TaskStatus.PENDING
        assert task.priority == Priority.P2
        assert task.schema_version == 1

    def test_task_model_requires_fields(self, valid_task_data):
        """TaskModel requires all mandatory fields."""
        for field in ["task_id", "goal_id", "task_type", "status", "priority"]:
            data = valid_task_data.copy()
            del data[field]
            with pytest.raises(ValidationError):
                TaskModel(**data)

    def test_task_model_defaults(self, valid_task_data):
        """TaskModel provides correct defaults."""
        task = TaskModel(**valid_task_data)
        assert task.dependencies == []
        assert task.blocked_by == []
        assert task.preemptible is False
        assert task.checkpoint_interval_seconds is None
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert task.estimated_cost_usd is None
        assert task.deadline is None
        assert task.agent_name is None

    def test_task_model_optional_fields(self, valid_task_data):
        """TaskModel accepts optional fields."""
        data = valid_task_data.copy()
        data["dependencies"] = ["task-000"]
        data["blocked_by"] = ["task-000"]
        data["preemptible"] = True
        data["checkpoint_interval_seconds"] = 300
        data["retry_count"] = 1
        data["max_retries"] = 5
        data["estimated_cost_usd"] = 0.5
        data["deadline"] = 1777777777.0
        data["agent_name"] = "test_agent"
        data["queued_at"] = datetime.now(timezone.utc)
        data["started_at"] = datetime.now(timezone.utc)
        data["completed_at"] = datetime.now(timezone.utc)

        task = TaskModel(**data)
        assert task.dependencies == ["task-000"]
        assert task.blocked_by == ["task-000"]
        assert task.preemptible is True
        assert task.checkpoint_interval_seconds == 300
        assert task.retry_count == 1
        assert task.max_retries == 5
        assert task.estimated_cost_usd == 0.5
        assert task.deadline == 1777777777.0
        assert task.agent_name == "test_agent"

    def test_task_model_forbids_extra_fields(self, valid_task_data):
        """TaskModel forbids extra fields."""
        data = valid_task_data.copy()
        data["unknown_field"] = "should fail"
        with pytest.raises(ValidationError):
            TaskModel(**data)


# ============================================================================
# GoalCreateRequest Tests
# ============================================================================


class TestGoalCreateRequest:
    """Test GoalCreateRequest input validation."""

    def test_goal_create_request_minimal(self):
        """GoalCreateRequest accepts minimal required fields."""
        request = GoalCreateRequest(
            title="New Goal",
            description="Description",
            goal_type=GoalType.MAINTENANCE,
            priority=Priority.P2,
            created_by="user123",
        )
        assert request.title == "New Goal"
        assert request.goal_type == GoalType.MAINTENANCE
        assert request.priority == Priority.P2

    def test_goal_create_request_with_optional(self):
        """GoalCreateRequest accepts optional fields."""
        request = GoalCreateRequest(
            title="New Goal",
            description="Description",
            goal_type=GoalType.RESEARCH,
            priority=Priority.P1,
            created_by="user123",
            objective_label="experiments",
            decomposition_template="research_template",
            budget_max_cost_usd=50.0,
            budget_max_tokens=500000,
        )
        assert request.objective_label == "experiments"
        assert request.budget_max_cost_usd == 50.0


# ============================================================================
# TaskCreateRequest Tests
# ============================================================================


class TestTaskCreateRequest:
    """Test TaskCreateRequest input validation."""

    def test_task_create_request_minimal(self):
        """TaskCreateRequest accepts minimal required fields."""
        request = TaskCreateRequest(
            goal_id="goal-123",
            task_type="analysis",
            priority=Priority.P2,
        )
        assert request.goal_id == "goal-123"
        assert request.task_type == "analysis"
        assert request.priority == Priority.P2

    def test_task_create_request_with_optional(self):
        """TaskCreateRequest accepts optional fields."""
        request = TaskCreateRequest(
            goal_id="goal-123",
            task_type="analysis",
            priority=Priority.P1,
            dependencies=["task-000"],
            preemptible=True,
            checkpoint_interval_seconds=600,
            estimated_cost_usd=1.0,
            deadline=1777777777.0,
        )
        assert request.dependencies == ["task-000"]
        assert request.preemptible is True
        assert request.checkpoint_interval_seconds == 600


# ============================================================================
# GovernanceMatrix Tests
# ============================================================================


class TestGovernanceMatrix:
    """Test GovernanceMatrix rules and enforcement."""

    def test_governance_matrix_can_create(self):
        """GovernanceMatrix.can_create enforces per-type rules."""
        matrix = GovernanceMatrix()

        # Maintenance and learning: auto-create allowed
        assert matrix.can_create(GoalType.MAINTENANCE, "any_user") is True
        assert matrix.can_create(GoalType.LEARNING, "any_user") is True

        # Research: auto-create allowed (but requires approval)
        assert matrix.can_create(GoalType.RESEARCH, "any_user") is True

        # Execution and system: human-only creation
        assert matrix.can_create(GoalType.EXECUTION, "agent") is False
        assert matrix.can_create(GoalType.SYSTEM, "agent") is False

    def test_governance_matrix_requires_approval(self):
        """GovernanceMatrix.requires_approval returns correct values."""
        matrix = GovernanceMatrix()

        # Maintenance and learning: auto-approved
        assert matrix.requires_approval(GoalType.MAINTENANCE) is False
        assert matrix.requires_approval(GoalType.LEARNING) is False

        # Research, execution, system: require approval
        assert matrix.requires_approval(GoalType.RESEARCH) is True
        assert matrix.requires_approval(GoalType.EXECUTION) is True
        assert matrix.requires_approval(GoalType.SYSTEM) is True

    def test_governance_matrix_max_active(self):
        """GovernanceMatrix.get_max_active returns correct caps."""
        matrix = GovernanceMatrix()

        assert matrix.get_max_active(GoalType.MAINTENANCE) == 10
        assert matrix.get_max_active(GoalType.LEARNING) == 10
        assert matrix.get_max_active(GoalType.RESEARCH) == 5
        assert matrix.get_max_active(GoalType.EXECUTION) == 3
        assert matrix.get_max_active(GoalType.SYSTEM) == 2

    def test_governance_rule_structure(self):
        """GovernanceRule has correct fields."""
        rule = GovernanceRule(
            goal_type=GoalType.MAINTENANCE,
            auto_create=True,
            auto_approve=True,
            max_active=10,
        )
        assert rule.goal_type == GoalType.MAINTENANCE
        assert rule.auto_create is True
        assert rule.auto_approve is True
        assert rule.max_active == 10
