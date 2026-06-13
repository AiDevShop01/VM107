"""
Goal service with lifecycle management and governance enforcement.

Manages full goal lifecycle:
- Creation with governance validation
- Lifecycle transitions (draft → proposed → approved → active → paused/completed/failed/cancelled)
- Activation triggers decomposition, DAG validation, task creation, queue population
- Task completion unblocks downstream tasks and auto-completes goals
- Pause/resume control task processing
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.scheduling.models import GoalModel, GoalCreateRequest, TaskModel
from core.scheduling.enums import GoalStatus, TaskStatus, GoalType, Priority
from core.scheduling.governance import GovernanceMatrix
from core.decomposition.engine import DecompositionEngine
from core.scheduling.dag import DAGValidator
from core.persistence.mongo_cache import MongoCachedCollection
from core.persistence.bulk_writer import TieredBulkWriter
from core.persistence.redis_queue import RedisPriorityQueue

logger = logging.getLogger(__name__)


class GoalServiceError(Exception):
    """Raised when goal service operation fails."""
    pass


class GoalService:
    """
    Goal lifecycle manager with governance enforcement.

    Handles creation, transitions, activation (triggers decomposition),
    pause/resume, completion, and task completion callbacks.
    """

    def __init__(
        self,
        goal_cache: MongoCachedCollection,
        task_cache: MongoCachedCollection,
        bulk_writer: TieredBulkWriter,
        decomposition_engine: DecompositionEngine,
        governance: GovernanceMatrix,
        dag_validator: DAGValidator,
        queue: RedisPriorityQueue
    ):
        """
        Initialize GoalService.

        Args:
            goal_cache: MongoCachedCollection for goal reads/writes
            task_cache: MongoCachedCollection for task reads/writes
            bulk_writer: TieredBulkWriter for critical writes
            decomposition_engine: DecompositionEngine for task DAG creation
            governance: GovernanceMatrix for creation/approval rules
            dag_validator: DAGValidator for dependency resolution
            queue: RedisPriorityQueue for task queueing
        """
        self.goal_cache = goal_cache
        self.task_cache = task_cache
        self.bulk_writer = bulk_writer
        self.decomposition_engine = decomposition_engine
        self.governance = governance
        self.dag_validator = dag_validator
        self.queue = queue

    def create_goal(
        self, request: GoalCreateRequest, creator: str
    ) -> GoalModel:
        """
        Create goal with governance validation.

        Auto-approve shortcuts:
        - maintenance/learning → directly to active
        - research → proposed (requires approval)
        - execution/system → draft (requires proposal + approval)

        Args:
            request: GoalCreateRequest with goal details
            creator: Creator ID (user or agent)

        Returns:
            GoalModel with generated goal_id

        Raises:
            GoalServiceError: If governance validation fails
        """
        # Validate governance
        current_active_count = self._count_active_goals(request.goal_type)
        is_valid, error_msg = self.governance.validate_goal_creation(
            request.goal_type, creator, current_active_count
        )
        if not is_valid:
            raise GoalServiceError(error_msg)

        # Generate goal_id
        goal_id = f"goal_{uuid.uuid4().hex[:12]}"

        # Determine initial status
        if request.goal_type in [GoalType.MAINTENANCE, GoalType.LEARNING]:
            status = GoalStatus.ACTIVE  # Auto-approve shortcut
        elif request.goal_type == GoalType.RESEARCH:
            status = GoalStatus.PROPOSED  # Requires approval
        else:
            status = GoalStatus.DRAFT  # Requires proposal + approval

        # Determine governance tier
        if self.governance.requires_approval(request.goal_type):
            governance_tier = "approval" if self.governance.can_create(request.goal_type, creator) else "human-only"
        else:
            governance_tier = "auto"

        # Create goal model
        now = datetime.now(timezone.utc)
        goal = GoalModel(
            goal_id=goal_id,
            title=request.title,
            description=request.description,
            goal_type=request.goal_type,
            status=status,
            priority=request.priority,
            objective_label=request.objective_label,
            decomposition_template=request.decomposition_template,
            created_by=creator,
            governance_tier=governance_tier,
            budget_max_cost_usd=request.budget_max_cost_usd,
            budget_max_tokens=request.budget_max_tokens,
            task_ids=[],
            created_at=now,
            updated_at=now,
            schema_version=1
        )

        # Write to MongoDB via critical write
        self.bulk_writer.write_critical(goal_id, goal.model_dump())

        logger.info(f"Created goal {goal_id} with status={status.value}, type={request.goal_type.value}")
        return goal

    def propose_goal(self, goal_id: str) -> GoalModel:
        """
        Transition draft → proposed.

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel

        Raises:
            GoalServiceError: If transition invalid
        """
        goal = self._get_goal(goal_id)
        if goal.status != GoalStatus.DRAFT:
            raise GoalServiceError(f"Cannot propose goal in status {goal.status.value}")

        # Update status
        goal.status = GoalStatus.PROPOSED
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.PROPOSED.value,
            "updated_at": goal.updated_at
        })

        logger.info(f"Proposed goal {goal_id}")
        return goal

    def approve_goal(self, goal_id: str) -> GoalModel:
        """
        Transition proposed → approved.

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel

        Raises:
            GoalServiceError: If transition invalid
        """
        goal = self._get_goal(goal_id)
        if goal.status != GoalStatus.PROPOSED:
            raise GoalServiceError(f"Cannot approve goal in status {goal.status.value}")

        # Update status
        goal.status = GoalStatus.APPROVED
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.APPROVED.value,
            "updated_at": goal.updated_at
        })

        logger.info(f"Approved goal {goal_id}")
        return goal

    def activate_goal(self, goal_id: str) -> GoalModel:
        """
        Activate goal: triggers decomposition, DAG validation, task creation, queueing.

        Transition: approved → active OR draft → active (auto-approve types)

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel with task_ids populated

        Raises:
            GoalServiceError: If transition invalid or DAG invalid
        """
        goal = self._get_goal(goal_id)

        # Validate transition
        if goal.status not in [GoalStatus.APPROVED, GoalStatus.DRAFT]:
            raise GoalServiceError(f"Cannot activate goal in status {goal.status.value}")

        # Trigger decomposition
        if not goal.decomposition_template:
            raise GoalServiceError(f"Goal {goal_id} missing decomposition_template")

        try:
            tasks = self.decomposition_engine.decompose(goal.model_dump())
        except Exception as e:
            raise GoalServiceError(f"Decomposition failed: {e}") from e

        # Validate DAG
        try:
            self.dag_validator.validate_and_order(tasks)
        except ValueError as e:
            raise GoalServiceError(f"Invalid DAG: {e}") from e

        # Create all tasks in MongoDB (bulk critical writes)
        task_ids = []
        for task_dict in tasks:
            task_id = task_dict["task_id"]
            task_ids.append(task_id)
            self.bulk_writer.write_critical(task_id, task_dict)

        # Queue runnable tasks (no dependencies)
        runnable_task_ids = self.dag_validator.find_runnable_tasks(tasks, set())
        for task_id in runnable_task_ids:
            # Initial score (would use scorer in real implementation)
            initial_score = 5.0
            self.queue.enqueue(task_id, initial_score)

        # Update goal
        goal.status = GoalStatus.ACTIVE
        goal.task_ids = task_ids
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.ACTIVE.value,
            "task_ids": task_ids,
            "updated_at": goal.updated_at
        })

        logger.info(f"Activated goal {goal_id} with {len(task_ids)} tasks ({len(runnable_task_ids)} queued)")
        return goal

    def pause_goal(self, goal_id: str) -> GoalModel:
        """
        Pause goal: transition active → paused, pause all running tasks.

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel

        Raises:
            GoalServiceError: If transition invalid
        """
        goal = self._get_goal(goal_id)
        if goal.status != GoalStatus.ACTIVE:
            raise GoalServiceError(f"Cannot pause goal in status {goal.status.value}")

        # Pause all running/queued tasks
        for task_id in goal.task_ids:
            task = self.task_cache.get(task_id)
            if task and task.get("status") in ["running", "queued", "RUNNING", "QUEUED"]:
                self.bulk_writer.write_critical(task_id, {
                    "status": TaskStatus.PENDING.value,
                    "updated_at": datetime.now(timezone.utc)
                })
                # Remove from queue
                self.queue.remove(task_id)

        # Update goal
        goal.status = GoalStatus.PAUSED
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.PAUSED.value,
            "updated_at": goal.updated_at
        })

        logger.info(f"Paused goal {goal_id}")
        return goal

    def resume_goal(self, goal_id: str) -> GoalModel:
        """
        Resume goal: transition paused → active, re-queue pending tasks.

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel

        Raises:
            GoalServiceError: If transition invalid
        """
        goal = self._get_goal(goal_id)
        if goal.status != GoalStatus.PAUSED:
            raise GoalServiceError(f"Cannot resume goal in status {goal.status.value}")

        # Re-queue all pending tasks
        for task_id in goal.task_ids:
            task = self.task_cache.get(task_id)
            if task and task.get("status") in ["pending", "PENDING"]:
                self.bulk_writer.write_critical(task_id, {
                    "status": TaskStatus.QUEUED.value,
                    "updated_at": datetime.now(timezone.utc)
                })
                # Re-enqueue
                initial_score = 5.0
                self.queue.enqueue(task_id, initial_score)

        # Update goal
        goal.status = GoalStatus.ACTIVE
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.ACTIVE.value,
            "updated_at": goal.updated_at
        })

        logger.info(f"Resumed goal {goal_id}")
        return goal

    def complete_goal(self, goal_id: str) -> GoalModel:
        """
        Complete goal: transition active → completed (only if all tasks terminal).

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel

        Raises:
            GoalServiceError: If transition invalid or tasks incomplete
        """
        goal = self._get_goal(goal_id)
        if goal.status != GoalStatus.ACTIVE:
            raise GoalServiceError(f"Cannot complete goal in status {goal.status.value}")

        # Check all tasks terminal
        if not self._all_tasks_terminal(goal.task_ids):
            raise GoalServiceError(f"Cannot complete goal {goal_id}: not all tasks are terminal")

        # Update goal
        goal.status = GoalStatus.COMPLETED
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.COMPLETED.value,
            "updated_at": goal.updated_at
        })

        logger.info(f"Completed goal {goal_id}")
        return goal

    def fail_goal(self, goal_id: str, reason: str) -> GoalModel:
        """
        Fail goal: transition active → failed, cancel all pending/queued tasks.

        Args:
            goal_id: Goal identifier
            reason: Failure reason

        Returns:
            Updated GoalModel

        Raises:
            GoalServiceError: If transition invalid
        """
        goal = self._get_goal(goal_id)
        if goal.status != GoalStatus.ACTIVE:
            raise GoalServiceError(f"Cannot fail goal in status {goal.status.value}")

        # Cancel all pending/queued tasks
        for task_id in goal.task_ids:
            task = self.task_cache.get(task_id)
            if task and task.get("status") in ["pending", "queued", "PENDING", "QUEUED"]:
                self.bulk_writer.write_critical(task_id, {
                    "status": TaskStatus.CANCELLED.value,
                    "updated_at": datetime.now(timezone.utc)
                })
                # Remove from queue
                self.queue.remove(task_id)

        # Update goal
        goal.status = GoalStatus.FAILED
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.FAILED.value,
            "updated_at": goal.updated_at,
            "failure_reason": reason
        })

        logger.info(f"Failed goal {goal_id}: {reason}")
        return goal

    def cancel_goal(self, goal_id: str) -> GoalModel:
        """
        Cancel goal: transition to cancelled, cancel all non-terminal tasks.

        Args:
            goal_id: Goal identifier

        Returns:
            Updated GoalModel
        """
        goal = self._get_goal(goal_id)

        # Cancel all non-terminal tasks
        for task_id in goal.task_ids:
            task = self.task_cache.get(task_id)
            if task and task.get("status") not in ["completed", "failed", "cancelled", "COMPLETED", "FAILED", "CANCELLED"]:
                self.bulk_writer.write_critical(task_id, {
                    "status": TaskStatus.CANCELLED.value,
                    "updated_at": datetime.now(timezone.utc)
                })
                # Remove from queue
                self.queue.remove(task_id)

        # Update goal
        goal.status = GoalStatus.CANCELLED
        goal.updated_at = datetime.now(timezone.utc)

        # Critical write
        self.bulk_writer.write_critical(goal_id, {
            "status": GoalStatus.CANCELLED.value,
            "updated_at": goal.updated_at
        })

        logger.info(f"Cancelled goal {goal_id}")
        return goal

    def on_task_completed(self, task_id: str) -> None:
        """
        Handle task completion: unblock downstream tasks, auto-complete goal if all terminal.

        Args:
            task_id: Task ID that completed
        """
        task = self.task_cache.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return

        goal_id = task.get("goal_id")
        if not goal_id:
            logger.warning(f"Task {task_id} missing goal_id")
            return

        goal = self._get_goal(goal_id)

        # Find tasks blocked by this task
        for candidate_task_id in goal.task_ids:
            candidate = self.task_cache.get(candidate_task_id)
            if not candidate:
                continue

            blocked_by = set(candidate.get("blocked_by", []))
            if task_id in blocked_by:
                # Remove from blocked_by
                blocked_by.remove(task_id)

                # If all deps resolved, transition blocked → queued
                if not blocked_by:
                    self.bulk_writer.write_critical(candidate_task_id, {
                        "status": TaskStatus.QUEUED.value,
                        "blocked_by": [],
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Re-score and enqueue
                    initial_score = 5.0  # Would use scorer in real implementation
                    self.queue.enqueue(candidate_task_id, initial_score)
                    logger.info(f"Unblocked task {candidate_task_id}")
                else:
                    # Update blocked_by
                    self.bulk_writer.write_critical(candidate_task_id, {
                        "blocked_by": list(blocked_by),
                        "updated_at": datetime.now(timezone.utc)
                    })

        # Check if all tasks terminal → auto-complete goal
        if self._all_tasks_terminal(goal.task_ids):
            try:
                self.complete_goal(goal_id)
                logger.info(f"Auto-completed goal {goal_id}")
            except GoalServiceError as e:
                logger.warning(f"Failed to auto-complete goal {goal_id}: {e}")

    def _get_goal(self, goal_id: str) -> GoalModel:
        """
        Fetch goal from cache and parse as GoalModel.

        Args:
            goal_id: Goal identifier

        Returns:
            GoalModel

        Raises:
            GoalServiceError: If goal not found
        """
        goal_dict = self.goal_cache.get(goal_id)
        if not goal_dict:
            raise GoalServiceError(f"Goal {goal_id} not found")

        # Strip Mongo-managed `_id` so Pydantic GoalModel (extra=forbid) parses cleanly.
        goal_dict.pop("_id", None)
        return GoalModel(**goal_dict)

    def _count_active_goals(self, goal_type: GoalType) -> int:
        """
        Count active goals of given type.

        Placeholder: would query MongoDB in real implementation.
        """
        return 0

    def _all_tasks_terminal(self, task_ids: list[str]) -> bool:
        """
        Check if all tasks are in terminal state.

        Args:
            task_ids: List of task IDs to check

        Returns:
            True if all tasks are completed/failed/cancelled
        """
        terminal_statuses = {"completed", "failed", "cancelled", "COMPLETED", "FAILED", "CANCELLED"}

        for task_id in task_ids:
            task = self.task_cache.get(task_id)
            if not task:
                return False
            if task.get("status") not in terminal_statuses:
                return False

        return True
