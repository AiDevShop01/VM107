"""
Interface protocols for AgentRunner execution engine.

Re-exports all interface protocols and no-op implementations.
"""
from core.interfaces.boundary import ExecutionBoundaryInterface, NoOpBoundary
from core.interfaces.progress_ledger import (
    ProgressLedgerInterface,
    NoOpProgressLedger,
)
from core.interfaces.stall_detector import (
    StallDetectorInterface,
    NoOpStallDetector,
)
from core.interfaces.task_ledger import TaskLedgerInterface, NoOpTaskLedger

__all__ = [
    "ExecutionBoundaryInterface",
    "NoOpBoundary",
    "ProgressLedgerInterface",
    "NoOpProgressLedger",
    "StallDetectorInterface",
    "NoOpStallDetector",
    "TaskLedgerInterface",
    "NoOpTaskLedger",
]
