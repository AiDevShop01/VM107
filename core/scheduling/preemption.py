"""
Cooperative pre-emption with 5-condition check and cooldown.

Implements P1-only pre-emption requiring ALL 5 conditions:
1. Incoming task is P1
2. SLA/deadline breach risk
3. No free worker available
4. Running task declared preemptible=True
5. Expected gain > cost × threshold

Max pre-emptions per cycle with cooldown prevents cascading interruptions.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
from core.scheduling.enums import Priority


@dataclass
class PreemptionResult:
    """Result of pre-emption check."""

    should_preempt: bool
    target_task_id: Optional[str]
    reason: str


class PreemptionManager:
    """
    Cooperative pre-emption manager with 5-condition check.

    Pre-emption is P1-only and requires ALL 5 conditions to be true.
    Tracks pre-emptions per cycle and enforces cooldown window.
    """

    def __init__(
        self,
        max_preemptions_per_cycle: int = 2,
        cooldown_seconds: float = 60.0
    ):
        """
        Initialize PreemptionManager.

        Args:
            max_preemptions_per_cycle: Maximum pre-emptions allowed per scheduler cycle
            cooldown_seconds: Cooldown window before task can be pre-empted again
        """
        self.max_preemptions_per_cycle = max_preemptions_per_cycle
        self.cooldown_seconds = cooldown_seconds

        # Internal state
        self.preemptions_this_cycle = 0
        self.cooldown_timestamps: dict[str, float] = {}

    def check_preemption(
        self,
        incoming_task: dict[str, Any],
        running_tasks: list[dict[str, Any]],
        available_workers: int,
        threshold: float,
    ) -> PreemptionResult:
        """
        Evaluate all 5 pre-emption conditions.

        Args:
            incoming_task: Task requesting pre-emption (must be P1)
            running_tasks: List of currently running tasks
            available_workers: Number of free workers
            threshold: Gain/cost threshold for pre-emption decision

        Returns:
            PreemptionResult with decision and reason
        """
        # Condition 1: Incoming task is P1
        priority = incoming_task.get("priority", Priority.P3)
        if isinstance(priority, str):
            priority = Priority(priority)
        if priority != Priority.P1:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason="Condition 1 failed: Incoming task is not P1"
            )

        # Condition 2: SLA/deadline breach risk
        if "deadline" not in incoming_task:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason="Condition 2 failed: No deadline risk (no deadline set)"
            )

        # Condition 3: No free worker available
        if available_workers > 0:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason="Condition 3 failed: Free worker available"
            )

        # Condition 4 & 5: Check for eligible target (preemptible + gain > cost * threshold)
        # Use current time from incoming_task if available, else use deadline as proxy
        current_time = incoming_task.get("deadline", 0.0)
        target_task_id = self.select_preemption_target(running_tasks, current_time)

        if target_task_id is None:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason="Condition 4 failed: No preemptible running tasks available"
            )

        # Find target task to check Condition 5
        target_task = next(
            (t for t in running_tasks if t.get("task_id") == target_task_id), None
        )
        if target_task is None:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason="Internal error: Selected target not found"
            )

        # Condition 5: Expected gain > cost × threshold
        estimated_gain = incoming_task.get("estimated_gain")
        estimated_cost = target_task.get("estimated_cost")

        if estimated_gain is None or estimated_cost is None:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason="Condition 5 failed: Missing gain or cost estimates"
            )

        if estimated_cost == 0:
            # Avoid division by zero - if cost is 0, any gain justifies pre-emption
            gain_ratio = float('inf')
        else:
            gain_ratio = estimated_gain / estimated_cost

        if gain_ratio <= threshold:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason=f"Condition 5 failed: Gain/cost ratio {gain_ratio:.2f} <= threshold {threshold}"
            )

        # Check max pre-emptions per cycle
        if self.preemptions_this_cycle >= self.max_preemptions_per_cycle:
            return PreemptionResult(
                should_preempt=False,
                target_task_id=None,
                reason=f"Max pre-emptions per cycle reached ({self.max_preemptions_per_cycle})"
            )

        # All 5 conditions met - approve pre-emption
        self.preemptions_this_cycle += 1
        return PreemptionResult(
            should_preempt=True,
            target_task_id=target_task_id,
            reason="Pre-emption approved: All 5 conditions met"
        )

    def select_preemption_target(
        self, running_tasks: list[dict[str, Any]], current_time: float
    ) -> Optional[str]:
        """
        Select pre-emption target from running tasks.

        Among preemptible tasks not in cooldown, selects lowest-priority task
        (highest P number). Tie-breaks by longest running time.

        Args:
            running_tasks: List of currently running tasks
            current_time: Current Unix timestamp

        Returns:
            task_id of selected target, or None if no eligible tasks
        """
        eligible_tasks = []

        for task in running_tasks:
            # Must be preemptible
            if not task.get("preemptible", False):
                continue

            # Must not be in cooldown
            task_id = task.get("task_id")
            if not self._is_eligible_for_preemption(task_id, current_time):
                continue

            eligible_tasks.append(task)

        if not eligible_tasks:
            return None

        # Sort by priority (lowest priority first), then by running time (longest first)
        def sort_key(task):
            priority = task.get("priority", Priority.P3)
            if isinstance(priority, str):
                priority = Priority(priority)

            # Priority sort key: P4=4, P3=3, P2=2, P1=1 (higher number = lower priority)
            priority_order = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
            priority_val = priority_order.get(priority.value, 3)

            # Running time: older tasks first (started_at ascending, so older = smaller)
            started_at = task.get("started_at", current_time)
            if hasattr(started_at, "timestamp"):
                started_at = started_at.timestamp()

            return (-priority_val, started_at)  # -priority_val for descending, started_at for ascending

        eligible_tasks.sort(key=sort_key)
        return eligible_tasks[0].get("task_id")

    def reset_cycle(self):
        """Reset pre-emptions counter at start of new scheduler cycle."""
        self.preemptions_this_cycle = 0

    def _record_preemption(self, task_id: str, timestamp: float):
        """
        Record pre-emption timestamp for cooldown tracking.

        Args:
            task_id: ID of task that was pre-empted
            timestamp: Unix timestamp when pre-emption occurred
        """
        self.cooldown_timestamps[task_id] = timestamp

    def _is_eligible_for_preemption(self, task_id: str, current_time: float) -> bool:
        """
        Check if task is eligible for pre-emption (not in cooldown).

        Args:
            task_id: ID of task to check
            current_time: Current Unix timestamp

        Returns:
            True if task can be pre-empted, False if in cooldown window
        """
        if task_id not in self.cooldown_timestamps:
            return True

        last_preempted = self.cooldown_timestamps[task_id]
        time_since_preemption = current_time - last_preempted
        return time_since_preemption > self.cooldown_seconds
