"""
Task scoring formula with bounded factors and mode bias.

Implements multiplicative core (P × G × B × U × R × F) with additive bonuses/penalties.
All factors bounded/clamped to prevent runaway scores. Mode bias adjusts weights per
behavioral mode. Anti-starvation guarantees via per-priority aging caps.
"""

from __future__ import annotations
import math
from typing import Any
from core.scheduling.enums import Priority, BehavioralMode, ResourcePolicy


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to [min_val, max_val] range."""
    return max(min_val, min(max_val, value))


class TaskScorer:
    """
    Task scoring engine with multiplicative formula and bounded aging.

    Score formula: score = P × G × B × U × R × F + bonuses - penalties
    - P = priority base (0.5-4.0): P1=4.0, P2=2.0, P3=1.0, P4=0.5
    - G = goal weight (0.5-2.0): linear from success_rate
    - B = brain weights (0.7-1.5): mode_bias * goal_override, clamped
    - U = urgency/deadline (1.0-2.0): sigmoid near deadline
    - R = readiness (0 if blocked, 1.0-1.2 if ready/just-unblocked)
    - F = fairness/age (1.0-2.0): bounded aging per priority
    """

    def __init__(self, brain_state: dict[str, Any], mode_config: dict[str, Any]):
        """
        Initialize TaskScorer.

        Args:
            brain_state: Current brain state (mode, resource_policy, scheduler_control)
            mode_config: Mode-specific bias configuration
        """
        self.brain_state = brain_state
        self.mode_config = mode_config

        # Aging parameters per priority (F_MAX, AGE_WINDOW_SECONDS)
        self.aging_params = {
            Priority.P1: {"F_MAX": 0.0, "AGE_WINDOW": 60},  # No aging
            Priority.P2: {"F_MAX": 0.2, "AGE_WINDOW": 180},  # Max 1.2
            Priority.P3: {"F_MAX": 0.5, "AGE_WINDOW": 300},  # Max 1.5
            Priority.P4: {"F_MAX": 0.3, "AGE_WINDOW": 600},  # Max 1.3
        }

    def score(
        self, task: dict[str, Any], goal: dict[str, Any], current_time: float
    ) -> float:
        """
        Compute bounded multiplicative score for a task.

        Args:
            task: Task dict with priority, status, queued_at, etc.
            goal: Goal dict with success_rate
            current_time: Current Unix timestamp

        Returns:
            Final score (0.0 if blocked, otherwise P*G*B*U*R*F + bonuses - penalties)
        """
        # Hard gate: blocked tasks score 0
        if task.get("blocked_by"):
            return 0.0

        # Compute multiplicative factors
        P = self._priority_base(task)
        G = self._goal_weight(goal)
        B = self._brain_weight(task, goal)
        U = self._urgency_factor(task, current_time)
        R = self._readiness_factor(task)
        F = self._aging_factor(task, current_time)

        # Multiplicative core
        base_score = P * G * B * U * R * F

        # Additive bonuses
        bonuses = 0.0
        bonuses += self._unblocks_many(task)
        bonuses += self._batch_locality(task)

        # Additive penalties
        penalties = 0.0
        penalties += 0.3 * task.get("retry_count", 0)  # -0.3 per retry
        if self.brain_state.get("resource_policy") == "constrained":
            penalties += 0.5  # Cost pressure penalty
        if (
            self.brain_state.get("mode") == BehavioralMode.STABILIZATION
            and task.get("risky", False)
        ):
            penalties += 0.5  # Risk penalty in stabilization

        return base_score + bonuses - penalties

    def score_batch(
        self,
        tasks: list[dict[str, Any]],
        goals: dict[str, dict[str, Any]],
        current_time: float,
    ) -> list[tuple[str, float]]:
        """
        Score multiple tasks efficiently and return sorted results.

        Args:
            tasks: List of task dicts (each must have task_id)
            goals: Dict mapping task_id to goal dict
            current_time: Current Unix timestamp

        Returns:
            Sorted list of (task_id, score) tuples, highest score first
        """
        results = []
        for task in tasks:
            task_id = task["task_id"]
            goal = goals.get(task_id, {"success_rate": 0.5})  # Default goal
            score = self.score(task, goal, current_time)
            results.append((task_id, score))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    # --- Factor computation methods ---

    def _priority_base(self, task: dict[str, Any]) -> float:
        """
        Compute priority base factor (P).

        Args:
            task: Task dict with priority field

        Returns:
            P in [0.5, 4.0] from Priority enum base_weight
        """
        priority = task.get("priority", Priority.P3)
        if isinstance(priority, str):
            priority = Priority(priority)
        return priority.base_weight

    def _goal_weight(self, goal: dict[str, Any]) -> float:
        """
        Compute goal weight factor (G) from success rate.

        Args:
            goal: Goal dict with success_rate field

        Returns:
            G in [0.5, 2.0] via linear interpolation
        """
        success_rate = goal.get("success_rate", 0.5)
        # Linear interpolation: 0.0 -> 0.5, 1.0 -> 2.0
        return 0.5 + (2.0 - 0.5) * success_rate

    def _brain_weight(self, task: dict[str, Any], goal: dict[str, Any]) -> float:
        """
        Compute brain weight factor (B) from mode bias and goal overrides.

        Args:
            task: Task dict with task_type, priority
            goal: Goal dict (for future goal_override support)

        Returns:
            B in [0.7, 1.5] from mode_bias, clamped
        """
        mode = self.brain_state.get("mode", BehavioralMode.EXPLORATION)
        mode_config = self.mode_config.get(mode.value if isinstance(mode, BehavioralMode) else mode, {})

        # Default bias = 1.0
        bias = 1.0

        # Apply mode-specific bias based on task_type
        task_type = task.get("task_type", "")
        if task_type in mode_config:
            bias = mode_config[task_type]

        # Apply priority-specific boosts (e.g., P1_boost in stabilization)
        priority = task.get("priority", Priority.P3)
        if isinstance(priority, str):
            priority = Priority(priority)
        priority_key = f"{priority.value}_boost"
        if priority_key in mode_config:
            bias = mode_config[priority_key]

        # Apply priority-specific suppression (e.g., P4_suppress in stabilization)
        suppress_key = f"{priority.value}_suppress"
        if suppress_key in mode_config:
            bias = mode_config[suppress_key]

        # Future: goal_override could multiply bias here

        # Clamp to [0.7, 1.5]
        return clamp(bias, 0.7, 1.5)

    def _urgency_factor(self, task: dict[str, Any], current_time: float) -> float:
        """
        Compute urgency/deadline factor (U) via sigmoid.

        Args:
            task: Task dict with optional deadline field
            current_time: Current Unix timestamp

        Returns:
            U in [1.0, 2.0] via sigmoid near deadline
        """
        deadline = task.get("deadline")
        if deadline is None:
            return 1.0

        # Time until deadline (in seconds)
        time_remaining = deadline - current_time
        if time_remaining <= 0:
            return 2.0  # Past deadline, max urgency

        # Sigmoid centered around 2 hours (7200s)
        # U = 1 + 1 / (1 + exp((t - 7200) / 3600))
        # When t=3600 (1hr): U ≈ 1.5
        # When t=86400 (24hr): U ≈ 1.0
        sigmoid_input = (time_remaining - 7200) / 3600
        urgency = 1.0 + 1.0 / (1.0 + math.exp(sigmoid_input))
        return clamp(urgency, 1.0, 2.0)

    def _readiness_factor(self, task: dict[str, Any]) -> float:
        """
        Compute readiness factor (R).

        Args:
            task: Task dict with blocked_by, just_unblocked flags

        Returns:
            R = 0 if blocked, 1.2 if just-unblocked, 1.0 if ready
        """
        if task.get("blocked_by"):
            return 0.0
        if task.get("just_unblocked", False):
            return 1.2
        return 1.0

    def _aging_factor(self, task: dict[str, Any], current_time: float) -> float:
        """
        Compute aging/fairness factor (F) with per-priority caps.

        Args:
            task: Task dict with priority, queued_at
            current_time: Current Unix timestamp

        Returns:
            F in [1.0, 1.0+F_MAX] based on wait time, capped per priority
        """
        queued_at = task.get("queued_at")
        if queued_at is None:
            return 1.0

        # Convert datetime to timestamp if needed
        if hasattr(queued_at, "timestamp"):
            queued_at = queued_at.timestamp()

        priority = task.get("priority", Priority.P3)
        if isinstance(priority, str):
            priority = Priority(priority)

        params = self.aging_params[priority]
        F_MAX = params["F_MAX"]
        AGE_WINDOW = params["AGE_WINDOW"]

        wait_time = current_time - queued_at
        if wait_time <= 0:
            return 1.0

        # F = 1.0 + min(F_MAX, wait_time / AGE_WINDOW)
        aging_boost = min(F_MAX, wait_time / AGE_WINDOW)
        return 1.0 + aging_boost

    # --- Bonus/penalty methods ---

    def _unblocks_many(self, task: dict[str, Any]) -> float:
        """
        Bonus for tasks that unblock many others.

        Args:
            task: Task dict with optional unblocks_count field

        Returns:
            +0.5 if unblocks_count >= 5, else 0.0
        """
        unblocks_count = task.get("unblocks_count", 0)
        return 0.5 if unblocks_count >= 5 else 0.0

    def _batch_locality(self, task: dict[str, Any]) -> float:
        """
        Bonus for tasks with same partition as running tasks.

        Args:
            task: Task dict with optional batch_locality flag

        Returns:
            +0.2 if batch_locality=True, else 0.0
        """
        return 0.2 if task.get("batch_locality", False) else 0.0
