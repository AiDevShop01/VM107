"""
Stall detector interface.

Defines protocol for detecting execution stalls and triggering replanning.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.execution_context import ExecutionContext


@runtime_checkable
class StallDetectorInterface(Protocol):
    """
    Protocol for stall detection.

    Implementations detect when execution is stalled (repetitive actions,
    no progress) and can trigger replanning.
    """

    async def check(self, context: ExecutionContext) -> bool:
        """
        Check if execution is stalled.

        Args:
            context: Current execution context

        Returns:
            True if stalled, False otherwise
        """
        ...

    async def trigger_replan(self) -> None:
        """
        Trigger replanning when stalled.

        Implementation-specific behavior for handling stall conditions.
        """
        ...


class NoOpStallDetector:
    """No-op stall detector that never detects stalls."""

    async def check(self, context: ExecutionContext) -> bool:
        """Always return False."""
        return False

    async def trigger_replan(self) -> None:
        """No-op trigger."""
        pass
