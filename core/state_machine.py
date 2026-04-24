"""
AgentRunner state machine.

Defines the 6-state execution lifecycle and valid transition rules.

States:
- IDLE: Agent available for new task
- RUNNING: Agent actively executing
- PAUSED: Execution paused (can resume)
- CANCELLED: Execution terminated (terminal state)
- COMPLETE: Task completed successfully
- FAILED: Task failed (can restart from IDLE)

Transition Rules:
- IDLE -> RUNNING (start execution)
- RUNNING -> PAUSED, COMPLETE, FAILED, CANCELLED
- PAUSED -> RUNNING (resume), CANCELLED
- FAILED -> IDLE (restart)
- COMPLETE -> IDLE (new task)
- CANCELLED -> [] (terminal state)
"""
from __future__ import annotations

from enum import Enum


class AgentState(Enum):
    """Agent execution states."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETE = "complete"
    FAILED = "failed"


ALLOWED_TRANSITIONS: dict[AgentState, list[AgentState]] = {
    AgentState.IDLE: [AgentState.RUNNING],
    AgentState.RUNNING: [
        AgentState.PAUSED,
        AgentState.COMPLETE,
        AgentState.FAILED,
        AgentState.CANCELLED,
    ],
    AgentState.PAUSED: [AgentState.RUNNING, AgentState.CANCELLED],
    AgentState.FAILED: [AgentState.IDLE],
    AgentState.COMPLETE: [AgentState.IDLE],
    AgentState.CANCELLED: [],  # Terminal state - no outgoing transitions
}


def validate_transition(from_state: AgentState, to_state: AgentState) -> bool:
    """
    Check if a state transition is allowed.

    Args:
        from_state: Current state
        to_state: Desired next state

    Returns:
        True if transition is valid, False otherwise
    """
    return to_state in ALLOWED_TRANSITIONS[from_state]


class InvalidTransitionError(Exception):
    """
    Exception raised when an invalid state transition is attempted.

    Attributes:
        from_state: The state being transitioned from
        to_state: The state being transitioned to
        reason: Human-readable explanation of why transition is invalid
    """

    def __init__(
        self,
        from_state: AgentState,
        to_state: AgentState,
        reason: str,
    ):
        """
        Initialize InvalidTransitionError.

        Args:
            from_state: Current state
            to_state: Attempted target state
            reason: Why the transition is invalid
        """
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(
            f"Invalid transition from {from_state.value} to {to_state.value}: {reason}"
        )
