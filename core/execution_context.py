"""
Execution context data contracts.

Defines dataclasses for tracking agent execution state, boundaries, steps, and transitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BoundaryStatus(Enum):
    """Execution boundary check status."""

    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"  # Keep for backward compat
    STEP_LIMIT_EXCEEDED = "step_limit_exceeded"
    TOKEN_LIMIT_EXCEEDED = "token_limit_exceeded"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    DAILY_BUDGET_EXCEEDED = "daily_budget_exceeded"

    def is_exceeded(self) -> bool:
        """Return True if this status represents any exceeded boundary."""
        return self in (
            BoundaryStatus.EXCEEDED,
            BoundaryStatus.STEP_LIMIT_EXCEEDED,
            BoundaryStatus.TOKEN_LIMIT_EXCEEDED,
            BoundaryStatus.COST_LIMIT_EXCEEDED,
            BoundaryStatus.TIME_LIMIT_EXCEEDED,
            BoundaryStatus.DAILY_BUDGET_EXCEEDED,
        )


@dataclass
class ExecutionContext:
    """
    Execution context tracking agent state and metrics.

    Tracks task identity, execution state, timing, resource consumption,
    and loop iterations.
    """

    task_id: str = ""
    step_id: str = ""
    state: str = "idle"
    start_time: float = 0.0
    step_count: int = 0
    token_count: int = 0
    cost_usd: float = 0.0
    loop_iterations: int = 0
    last_transition: datetime | None = None


@dataclass
class StepResult:
    """
    Result from a single execution step.

    Captures step identity, outcome, and arbitrary metadata.
    """

    step_id: str
    outcome: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StateTransition:
    """
    Record of a state transition event.

    Captures transition metadata for audit trail and debugging.
    """

    event: str
    from_state: str
    to_state: str
    reason: str
    timestamp: str
    agent_id: str
    context_id: str
