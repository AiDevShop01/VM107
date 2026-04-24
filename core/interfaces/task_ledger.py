"""
Task ledger interface.

Defines protocol for task plan storage and updates.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TaskLedgerInterface(Protocol):
    """
    Protocol for task plan management.

    Implementations provide task plan retrieval and update operations.
    """

    async def get_plan(self, task_id: str) -> dict:
        """
        Retrieve task plan.

        Args:
            task_id: Task identifier

        Returns:
            Task plan dictionary
        """
        ...

    async def update(self, task_id: str, data: dict) -> None:
        """
        Update task data.

        Args:
            task_id: Task identifier
            data: Update data
        """
        ...


class NoOpTaskLedger:
    """No-op task ledger that returns empty plans."""

    async def get_plan(self, task_id: str) -> dict:
        """Return empty dict."""
        return {}

    async def update(self, task_id: str, data: dict) -> None:
        """No-op update."""
        pass
