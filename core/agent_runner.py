"""
AgentRunner execution engine.

Manages agent lifecycle with state machine control, structured logging,
and execution boundary enforcement.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.execution_context import (
    BoundaryStatus,
    ExecutionContext,
    StateTransition,
    StepResult,
)
from core.interfaces import (
    ExecutionBoundaryInterface,
    NoOpBoundary,
    NoOpProgressLedger,
    NoOpStallDetector,
    NoOpTaskLedger,
    ProgressLedgerInterface,
    StallDetectorInterface,
    TaskLedgerInterface,
)
from core.state_machine import AgentState, InvalidTransitionError, validate_transition

logger = logging.getLogger("agentrunner")


class AgentRunner:
    """
    Execution engine wrapping agent lifecycle with state machine control.

    Manages state transitions, execution context, structured logging,
    and integration with boundary checks, ledgers, and stall detection.

    Attributes:
        state: Current agent state (read-only property)
        execution_context: Execution metrics and state
        agent: Agent Zero agent reference
        task_ledger: Task plan management interface
        progress_ledger: Progress tracking interface
        boundary: Execution boundary check interface
        stall_detector: Stall detection interface
    """

    def __init__(
        self,
        agent: Any,  # Agent Zero agent reference (typed as Any to avoid import)
        task_ledger: TaskLedgerInterface | None = None,
        progress_ledger: ProgressLedgerInterface | None = None,
        boundary: ExecutionBoundaryInterface | None = None,
        stall_detector: StallDetectorInterface | None = None,
    ):
        """
        Initialize AgentRunner.

        Args:
            agent: Agent Zero agent reference
            task_ledger: Task plan management (defaults to NoOpTaskLedger)
            progress_ledger: Progress tracking (defaults to NoOpProgressLedger)
            boundary: Execution boundary checks (defaults to NoOpBoundary)
            stall_detector: Stall detection (defaults to NoOpStallDetector)
        """
        self.agent = agent
        self._state = AgentState.IDLE
        self.execution_context = ExecutionContext()
        self._cleaned_up = False

        # Use no-op defaults if None provided
        self.task_ledger = task_ledger if task_ledger is not None else NoOpTaskLedger()
        self.progress_ledger = (
            progress_ledger if progress_ledger is not None else NoOpProgressLedger()
        )
        self.boundary = boundary if boundary is not None else NoOpBoundary()
        self.stall_detector = (
            stall_detector if stall_detector is not None else NoOpStallDetector()
        )

    @property
    def state(self) -> AgentState:
        """Get current agent state (read-only)."""
        return self._state

    async def start(self) -> None:
        """
        Start execution (IDLE -> RUNNING).

        Initializes execution context with start time.

        Raises:
            InvalidTransitionError: If not in IDLE state
        """
        await self.transition(AgentState.RUNNING, "Starting execution")
        self.execution_context.start_time = time.time()

    async def transition(self, to_state: AgentState, reason: str) -> None:
        """
        Transition to a new state.

        Validates transition, updates state, logs structured JSON event,
        and updates execution context.

        Args:
            to_state: Target state
            reason: Human-readable transition reason

        Raises:
            InvalidTransitionError: If transition is not allowed
        """
        # Validate transition
        if not validate_transition(self._state, to_state):
            raise InvalidTransitionError(self._state, to_state, reason)

        # Capture current state for logging
        from_state = self._state

        # Update state
        self._state = to_state

        # Update execution context
        self.execution_context.state = to_state.value
        self.execution_context.last_transition = datetime.now(timezone.utc)

        # Create structured log payload with ISO 8601 timestamp
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        transition_event = StateTransition(
            event="state_transition",
            from_state=from_state.value,
            to_state=to_state.value,
            reason=reason,
            timestamp=timestamp,
            agent_id=self.agent.agent_name,
            context_id=self.agent.context.id,
        )

        # Log as structured JSON
        log_data = {
            "event": transition_event.event,
            "from_state": transition_event.from_state,
            "to_state": transition_event.to_state,
            "reason": transition_event.reason,
            "timestamp": transition_event.timestamp,
            "agent_id": transition_event.agent_id,
            "context_id": transition_event.context_id,
        }
        logger.info(json.dumps(log_data))

    async def run_step(self) -> StepResult | None:
        """
        Execute a single step.

        Returns None if not in RUNNING state. Otherwise checks boundary,
        checks for stalls, increments step count, and returns result.

        Returns:
            StepResult if step executed, None if not running

        Note:
            Automatically transitions to FAILED if boundary exceeded.
        """
        # Only run if in RUNNING state
        if self._state != AgentState.RUNNING:
            return None

        # Check execution boundary
        boundary_status = await self.boundary.check(self.execution_context)
        if boundary_status == BoundaryStatus.EXCEEDED:
            await self.fail("Execution boundary exceeded")
            return None

        # Check for stalls
        await self.stall_detector.check(self.execution_context)

        # Increment step count
        self.execution_context.step_count += 1

        # Return step result
        return StepResult(
            step_id=f"step_{self.execution_context.step_count}",
            outcome="ok",
            metadata={},
        )

    async def pause(self) -> None:
        """
        Pause execution (RUNNING -> PAUSED).

        Execution context is preserved (step_count, token_count unchanged).

        Raises:
            InvalidTransitionError: If not in RUNNING state
        """
        await self.transition(AgentState.PAUSED, "Pausing execution")

    async def resume(self) -> None:
        """
        Resume execution (PAUSED -> RUNNING).

        Execution context is preserved (step_count, token_count unchanged).

        Raises:
            InvalidTransitionError: If not in PAUSED state
        """
        await self.transition(AgentState.RUNNING, "Resuming execution")

    async def cancel(self) -> None:
        """
        Cancel execution (RUNNING or PAUSED -> CANCELLED).

        Terminal state - cannot restart. Calls cleanup().

        Raises:
            InvalidTransitionError: If in IDLE, COMPLETE, FAILED, or CANCELLED state
        """
        await self.transition(AgentState.CANCELLED, "Cancelling execution")
        await self.cleanup()

    async def complete(self) -> None:
        """
        Mark execution complete (RUNNING -> COMPLETE).

        Raises:
            InvalidTransitionError: If not in RUNNING state
        """
        await self.transition(AgentState.COMPLETE, "Execution completed successfully")

    async def fail(self, reason: str) -> None:
        """
        Mark execution failed (RUNNING -> FAILED).

        Args:
            reason: Failure reason

        Raises:
            InvalidTransitionError: If not in RUNNING state
        """
        await self.transition(AgentState.FAILED, f"Execution failed: {reason}")

    async def reset(self) -> None:
        """
        Reset to IDLE (FAILED or COMPLETE -> IDLE).

        Clears execution context to defaults.

        Raises:
            InvalidTransitionError: If not in FAILED or COMPLETE state
        """
        await self.transition(AgentState.IDLE, "Resetting to idle")

        # Reset execution context to defaults
        self.execution_context = ExecutionContext()

    async def cleanup(self) -> None:
        """
        Clean up resources.

        Idempotent - can be called multiple times safely.
        """
        if self._cleaned_up:
            return

        # Cleanup logic here (currently no resources to clean)
        # Future: close connections, release locks, etc.

        self._cleaned_up = True
