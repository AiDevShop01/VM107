"""
Enums for Goal/Task scheduling system.

Provides lifecycle state enums with transition validation, goal types,
priority levels with weights, and system behavioral modes.
"""

from __future__ import annotations
from enum import Enum


class GoalStatus(str, Enum):
    """Goal lifecycle states (8 states)."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def validate_transition(cls, from_state: GoalStatus, to_state: GoalStatus) -> bool:
        """Validate if transition from_state -> to_state is allowed."""
        allowed = _GOAL_ALLOWED_TRANSITIONS.get(from_state, [])
        return to_state in allowed


class TaskStatus(str, Enum):
    """Task lifecycle states (7 states)."""

    PENDING = "pending"
    BLOCKED = "blocked"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def validate_transition(cls, from_state: TaskStatus, to_state: TaskStatus) -> bool:
        """Validate if transition from_state -> to_state is allowed."""
        allowed = _TASK_ALLOWED_TRANSITIONS.get(from_state, [])
        return to_state in allowed


class GoalType(str, Enum):
    """Goal classification types (5 types)."""

    MAINTENANCE = "maintenance"
    LEARNING = "learning"
    RESEARCH = "research"
    EXECUTION = "execution"
    SYSTEM = "system"


class Priority(str, Enum):
    """Priority levels with base weights for scoring."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"

    @property
    def base_weight(self) -> float:
        """Base weight for priority scoring."""
        weights = {
            "P1": 4.0,
            "P2": 2.0,
            "P3": 1.0,
            "P4": 0.5,
        }
        return weights[self.value]


class BehavioralMode(str, Enum):
    """Brain behavioral modes (3 modes)."""

    EXPLORATION = "exploration"
    EXPLOITATION = "exploitation"
    STABILIZATION = "stabilization"


class ResourcePolicy(str, Enum):
    """Resource allocation policies (2 policies)."""

    NORMAL = "normal"
    CONSTRAINED = "constrained"


# Transition tables (defined outside enum to avoid being treated as members)
_GOAL_ALLOWED_TRANSITIONS: dict[GoalStatus, list[GoalStatus]] = {
    GoalStatus.DRAFT: [GoalStatus.PROPOSED, GoalStatus.ACTIVE],  # active = shortcut
    GoalStatus.PROPOSED: [GoalStatus.APPROVED],
    GoalStatus.APPROVED: [GoalStatus.ACTIVE],
    GoalStatus.ACTIVE: [
        GoalStatus.PAUSED,
        GoalStatus.COMPLETED,
        GoalStatus.FAILED,
        GoalStatus.CANCELLED,
    ],
    GoalStatus.PAUSED: [GoalStatus.ACTIVE, GoalStatus.CANCELLED],
    GoalStatus.COMPLETED: [],  # terminal
    GoalStatus.FAILED: [],  # terminal
    GoalStatus.CANCELLED: [],  # terminal
}

_TASK_ALLOWED_TRANSITIONS: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.PENDING: [TaskStatus.BLOCKED, TaskStatus.QUEUED],
    TaskStatus.BLOCKED: [TaskStatus.QUEUED],
    TaskStatus.QUEUED: [TaskStatus.RUNNING],
    TaskStatus.RUNNING: [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED],
    TaskStatus.COMPLETED: [],  # terminal
    TaskStatus.FAILED: [],  # terminal
    TaskStatus.CANCELLED: [],  # terminal
}
