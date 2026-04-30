"""
Scheduler orchestrator with brain integration, batch selection, and degraded mode.

Implements deterministic scheduling cycle:
1. Brain update cycle with cadence guard
2. Hard gates (blocked goals, budget exceeded)
3. Task scoring and queue updates
4. Batch dequeue and dispatch
5. Pre-emption check
6. Periodic reconciliation

Degrades gracefully when Redis unavailable (stabilization mode + throttling).
"""

import logging
import time
from typing import Any, Callable, Optional

from core.scheduling.brain import BrainLayer, SchedulerControl
from core.scheduling.scoring import TaskScorer
from core.scheduling.preemption import PreemptionManager
from core.scheduling.dag import DAGValidator
from core.persistence.redis_queue import RedisPriorityQueue, SchedulerDegradedError
from core.persistence.mongo_cache import MongoCachedCollection
from core.persistence.bulk_writer import TieredBulkWriter
from core.persistence.reconciliation import ReconciliationJob
from core.scheduling.enums import BehavioralMode, ResourcePolicy, TaskStatus

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Main scheduler orchestrator with brain-integrated execution.

    Coordinates brain updates, task scoring, batch selection, dispatch,
    pre-emption, and reconciliation. Degrades gracefully on Redis failure.
    """

    def __init__(
        self,
        brain: BrainLayer,
        scorer: TaskScorer,
        queue: RedisPriorityQueue,
        preemption_mgr: PreemptionManager,
        task_cache: MongoCachedCollection,
        goal_cache: MongoCachedCollection,
        bulk_writer: TieredBulkWriter,
        reconciliation: ReconciliationJob,
        dag_validator: DAGValidator,
        max_workers: int,
        worker_callback: Callable[[str, dict], None],
        loop_interval_seconds: float = 5.0,
        brain_cadence_seconds: float = 5.0,
        reconciliation_interval_seconds: float = 60.0,
        batch_size: int = 5
    ):
        """
        Initialize Scheduler.

        Args:
            brain: BrainLayer for policy control
            scorer: TaskScorer for priority scoring
            queue: RedisPriorityQueue for task queue
            preemption_mgr: PreemptionManager for pre-emption checks
            task_cache: MongoCachedCollection for task reads
            goal_cache: MongoCachedCollection for goal reads
            bulk_writer: TieredBulkWriter for state writes
            reconciliation: ReconciliationJob for drift healing
            dag_validator: DAGValidator for dependency resolution
            max_workers: Maximum concurrent workers
            worker_callback: Function(task_id, envelope) to dispatch tasks
            loop_interval_seconds: Scheduler loop interval
            brain_cadence_seconds: Minimum time between brain updates
            reconciliation_interval_seconds: Time between reconciliation runs
            batch_size: Maximum tasks to dequeue per cycle
        """
        self.brain = brain
        self.scorer = scorer
        self.queue = queue
        self.preemption_mgr = preemption_mgr
        self.task_cache = task_cache
        self.goal_cache = goal_cache
        self.bulk_writer = bulk_writer
        self.reconciliation = reconciliation
        self.dag_validator = dag_validator
        self.max_workers = max_workers
        self.worker_callback = worker_callback
        self.loop_interval_seconds = loop_interval_seconds
        self.brain_cadence_seconds = brain_cadence_seconds
        self.reconciliation_interval_seconds = reconciliation_interval_seconds
        self.batch_size = batch_size

        # Internal state
        self._last_brain_update = 0.0
        self._last_reconciliation = 0.0
        self._running_tasks: dict[str, dict] = {}  # task_id -> task dict
        self._degraded_mode = False
        self._consecutive_healthy_checks = 0

    def run_cycle(self) -> None:
        """
        Execute single scheduler cycle.

        Steps:
        1. Reset pre-emption manager
        2. Drain hot signals
        3. Brain update (if cadence guard allows)
        4. Apply hard gates
        5. Score and update queue
        6. Dequeue batch
        7. Dispatch tasks
        8. Check pre-emption
        9. Reconciliation (periodic)
        10. Flush buffers
        """
        current_time = time.time()

        try:
            # 1. Reset pre-emption manager for new cycle
            self.preemption_mgr.reset_cycle()

            # 2. Drain hot signals (placeholder - signals integrated in brain update)
            hot_signals = []

            # 3. Brain update cycle with cadence guard
            if current_time - self._last_brain_update >= self.brain_cadence_seconds:
                self.brain.update_cycle(hot_signals)
                self._last_brain_update = current_time

            # 4. Get scheduler control from brain
            scheduler_control = self.brain.get_scheduler_control()

            # 5. Apply hard gates: filter blocked goals and budget-exceeded tasks
            runnable_tasks = self._fetch_runnable_tasks(scheduler_control)

            # 6. Score all runnable tasks
            scored_tasks = self._score_tasks(runnable_tasks, current_time)

            # 7. Update ZSET scores for all tasks
            self._update_queue_scores(scored_tasks)

            # 8. Dequeue batch
            available_slots = scheduler_control.max_concurrent_tasks - len(self._running_tasks)
            dequeue_count = min(available_slots, self.batch_size)

            if dequeue_count > 0:
                dequeued = self.queue.dequeue_batch(dequeue_count)

                # 9. Dispatch tasks
                for task_id, score in dequeued:
                    self._dispatch_task(task_id, current_time)

            # 10. Check pre-emption (if P1 task in queue and no free workers)
            if available_slots == 0:
                self._check_preemption(scheduler_control, current_time)

            # 11. Run reconciliation (periodic)
            if current_time - self._last_reconciliation >= self.reconciliation_interval_seconds:
                result = self.reconciliation.run()
                logger.info(f"Reconciliation: healed={result.healed_tasks}, removed={result.removed_stale}, duration={result.duration_ms}ms")
                self._last_reconciliation = current_time

            # 12. Flush bulk writer buffers
            self.bulk_writer.flush_all()

            # Track Redis health for degraded mode recovery
            if self._degraded_mode:
                self._consecutive_healthy_checks += 1
                if self._consecutive_healthy_checks >= 3:
                    self._restore_normal_mode()

        except SchedulerDegradedError as e:
            logger.error(f"Scheduler degraded: {e}")
            self._enter_degraded_mode()

    def _fetch_runnable_tasks(self, scheduler_control: SchedulerControl) -> list[dict]:
        """
        Fetch runnable tasks from cache with hard gates applied.

        Args:
            scheduler_control: Current scheduler control policy

        Returns:
            List of task dicts eligible for scoring
        """
        # Placeholder: fetch tasks from task_cache with status=queued
        # Real implementation would query MongoDB or use cached list
        # For now, return empty list (actual task fetching implemented in Plan 07)
        return []

    def _score_tasks(self, tasks: list[dict], current_time: float) -> list[tuple[str, float]]:
        """
        Score all runnable tasks using TaskScorer.

        Args:
            tasks: List of task dicts
            current_time: Current Unix timestamp

        Returns:
            List of (task_id, score) tuples
        """
        if not tasks:
            return []

        # Build goal cache for scoring
        goals = {}
        for task in tasks:
            goal_id = task.get("goal_id")
            if goal_id and goal_id not in goals:
                goal = self.goal_cache.get(goal_id)
                if goal:
                    goals[task["task_id"]] = goal

        # Score batch
        return self.scorer.score_batch(tasks, goals, current_time)

    def _update_queue_scores(self, scored_tasks: list[tuple[str, float]]) -> None:
        """
        Update Redis ZSET scores for all scored tasks.

        Args:
            scored_tasks: List of (task_id, score) tuples
        """
        for task_id, score in scored_tasks:
            try:
                self.queue.update_score(task_id, score)
            except SchedulerDegradedError:
                raise  # Propagate to trigger degraded mode
            except Exception as e:
                logger.warning(f"Failed to update score for {task_id}: {e}")

    def _dispatch_task(self, task_id: str, current_time: float) -> None:
        """
        Dispatch task to worker with brain context envelope.

        Args:
            task_id: Task ID to dispatch
            current_time: Current Unix timestamp
        """
        # Fetch task from cache
        task = self.task_cache.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found in cache, skipping dispatch")
            return

        # Transition to running
        task["status"] = TaskStatus.RUNNING.value
        task["started_at"] = current_time

        # Write critical state change
        self.bulk_writer.write_critical(task_id, {
            "status": TaskStatus.RUNNING.value,
            "started_at": current_time
        })

        # Track as running
        self._running_tasks[task_id] = task

        # Build task envelope with brain context
        brain_context = self.brain.get_brain_context()
        envelope = {
            "task_id": task_id,
            "task": task,
            "brain_context": brain_context
        }

        # Dispatch to worker
        try:
            self.worker_callback(task_id, envelope)
            logger.info(f"Dispatched task {task_id} with mode={brain_context['mode']}")
        except Exception as e:
            logger.error(f"Failed to dispatch task {task_id}: {e}")
            # Mark as failed
            self.bulk_writer.write_critical(task_id, {
                "status": TaskStatus.FAILED.value,
                "completed_at": current_time
            })
            self._running_tasks.pop(task_id, None)

    def _check_preemption(self, scheduler_control: SchedulerControl, current_time: float) -> None:
        """
        Check for P1 pre-emption opportunity.

        Args:
            scheduler_control: Current scheduler control policy
            current_time: Current Unix timestamp
        """
        if not scheduler_control.preemption_enabled:
            return

        # Peek top task in queue
        top_tasks = self.queue.peek_top(1)
        if not top_tasks:
            return

        task_id, score = top_tasks[0]
        incoming_task = self.task_cache.get(task_id)
        if not incoming_task:
            return

        # Check pre-emption
        running_tasks_list = list(self._running_tasks.values())
        result = self.preemption_mgr.check_preemption(
            incoming_task=incoming_task,
            running_tasks=running_tasks_list,
            available_workers=0,  # No free workers by definition
            threshold=scheduler_control.preemption_threshold
        )

        if result.should_preempt:
            logger.info(f"Pre-emption approved: {result.reason}")
            # Flag target task for pre-emption (actual pre-emption handled by AgentRunner)
            target_task = self._running_tasks.get(result.target_task_id)
            if target_task:
                self.bulk_writer.write_important(result.target_task_id, {
                    "preemption_requested": True,
                    "preemption_requested_at": current_time
                })

    def _enter_degraded_mode(self) -> None:
        """
        Enter degraded mode: stabilization + throttling.

        Reduces concurrency, disables expansion, increases loop interval.
        """
        if self._degraded_mode:
            return  # Already degraded

        logger.warning("Entering degraded mode: Redis unavailable")
        self._degraded_mode = True
        self._consecutive_healthy_checks = 0

        # Switch brain to stabilization mode
        # (actual brain mode switching would require brain.set_mode() method)
        # For now, just log the event
        logger.info("Degraded mode: Switching to stabilization + constrained resource policy")

        # Reduce max_workers
        self.max_workers = 2

        # Increase loop interval
        self.loop_interval_seconds = 10.0

    def _restore_normal_mode(self) -> None:
        """
        Restore normal mode after N consecutive healthy checks.
        """
        logger.info("Restoring normal mode: Redis healthy for 3+ cycles")
        self._degraded_mode = False
        self._consecutive_healthy_checks = 0

        # Restore defaults (would be from config in real implementation)
        self.max_workers = 5
        self.loop_interval_seconds = 5.0

    def get_running_count(self) -> int:
        """Get count of currently running tasks."""
        return len(self._running_tasks)

    def task_completed(self, task_id: str) -> None:
        """
        Mark task as completed and remove from running set.

        Args:
            task_id: Task ID that completed
        """
        self._running_tasks.pop(task_id, None)
