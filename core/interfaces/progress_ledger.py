"""
Progress ledger interface.

Defines protocol for tracking execution progress and determining next actions.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.execution_context import ExecutionContext, StepResult


@runtime_checkable
class ProgressLedgerInterface(Protocol):
    """
    Protocol for execution progress tracking.

    Implementations determine next actions and record step results.
    """

    async def get_next_action(self, context: ExecutionContext) -> dict | None:
        """
        Determine next action based on context.

        Args:
            context: Current execution context

        Returns:
            Next action dict or None if no action needed
        """
        ...

    async def record_step(self, result: StepResult) -> None:
        """
        Record step execution result.

        Args:
            result: Step result to record
        """
        ...


class NoOpProgressLedger:
    """No-op progress ledger that returns None."""

    async def get_next_action(self, context: ExecutionContext) -> dict | None:
        """Return None."""
        return None

    async def record_step(self, result: StepResult) -> None:
        """No-op record."""
        pass
