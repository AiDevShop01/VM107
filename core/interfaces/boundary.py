"""
Execution boundary interface.

Defines protocol for checking execution boundaries (time, cost, tokens).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.execution_context import BoundaryStatus, ExecutionContext


@runtime_checkable
class ExecutionBoundaryInterface(Protocol):
    """
    Protocol for execution boundary checking.

    Implementations validate whether execution should continue based on
    resource consumption, time limits, or other constraints.
    """

    async def check(self, context: ExecutionContext) -> BoundaryStatus:
        """
        Check if execution is within boundaries.

        Args:
            context: Current execution context with metrics

        Returns:
            BoundaryStatus indicating whether execution should continue
        """
        ...


class NoOpBoundary:
    """No-op boundary checker that always returns OK."""

    async def check(self, context: ExecutionContext) -> BoundaryStatus:
        """Always return BoundaryStatus.OK."""
        return BoundaryStatus.OK
