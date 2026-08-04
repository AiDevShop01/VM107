"""
Progress ledger interface.

Defines protocol for tracking execution progress and determining next actions.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from core.execution_context import ExecutionContext, StepResult
from emitters.source_health_registry import SourceHealthRegistry

# Import pymongo at module level for mockability
try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None

logger = logging.getLogger(__name__)


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


class MongoProgressLedger:
    """
    MongoDB-backed progress ledger with batched writes.

    Uses TieredBulkWriter pattern for efficient progress tracking.
    Progress updates are Tier 2 (important, batched 2-5s).
    """

    def __init__(self, mongo_uri: str, database: str = "fingpt_agents"):
        """
        Initialize MongoDB progress ledger.

        Args:
            mongo_uri: MongoDB connection URI
            database: Database name (default: fingpt_agents)
        """
        self._mongodb_available = False
        self._client = None
        self._db = None
        self._progress = None

        # Tier 2 write buffer (important writes, batched)
        self._buffer = deque(maxlen=200)  # Ring buffer cap
        self._buffer_max_size = 100
        self._buffer_max_seconds = 5.0
        self._last_flush = time.time()

        if MongoClient is None:
            logger.warning(
                "pymongo not available. MongoProgressLedger will behave like NoOpProgressLedger. "
                "Install with: pip install pymongo"
            )
            return

        try:
            # serverSelectionTimeoutMS bounds the (lazy) first op so a down
            # Mongo fast-fails instead of hanging (SC-1).
            self._client = MongoClient(
                mongo_uri,
                retryWrites=True,
                w="majority",
                serverSelectionTimeoutMS=int(os.getenv("A0_MONGO_TIMEOUT_MS", "5000")),
            )
            self._db = self._client[database]
            self._progress = self._db["agent_progress"]
            self._mongodb_available = True
            SourceHealthRegistry.get_shared_instance().report("mongo", available=True)
            logger.info(f"MongoProgressLedger initialized with database: {database}")
        except Exception as e:
            # Match this module's existing degrade-to-NoOp idiom; emit the
            # health signal alongside the warning (D-07).
            SourceHealthRegistry.get_shared_instance().report(
                "mongo", available=False, failure_reason=str(e)
            )
            logger.warning(
                f"MongoDB connection failed: {e}. "
                "MongoProgressLedger will behave like NoOpProgressLedger."
            )

    async def get_next_action(self, context: ExecutionContext) -> dict | None:
        """
        Determine next action based on task progress.

        Args:
            context: Current execution context

        Returns:
            Next action dict or None if task complete
        """
        if not self._mongodb_available or not context.task_id:
            return None

        try:
            # Fetch progress document
            progress_doc = self._progress.find_one({"_id": context.task_id})
            if not progress_doc:
                # No progress yet, return None (task should start from beginning)
                return None

            # Check if task is complete
            if progress_doc.get("status") == "COMPLETED":
                return None

            # Determine next action based on step count
            current_step = progress_doc.get("step_count", 0)
            total_steps = progress_doc.get("total_expected_steps")

            if total_steps is not None and current_step >= total_steps:
                return None

            # Return next action from task plan
            next_action = progress_doc.get("next_action")
            if next_action:
                return next_action

            return None

        except Exception as e:
            logger.error(f"Failed to get next action for task {context.task_id}: {e}")
            return None

    async def record_step(self, result: StepResult) -> None:
        """
        Record step result with batched writes.

        Uses Tier 2 batching (100 entries or 5s).

        Args:
            result: Step result to record
        """
        if not self._mongodb_available:
            return

        try:
            # Extract metadata for delta tracking
            metadata = result.metadata or {}
            token_count_delta = metadata.get("token_count_delta", 0)
            cost_usd_delta = metadata.get("cost_usd_delta", 0.0)

            # Buffer step result
            step_entry = {
                "step_id": result.step_id,
                "outcome": result.outcome,
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc),
                "token_count_delta": token_count_delta,
                "cost_usd_delta": cost_usd_delta
            }

            self._buffer.append(step_entry)

            # Check flush triggers
            if len(self._buffer) >= self._buffer_max_size:
                self._flush_buffer()
            elif time.time() - self._last_flush >= self._buffer_max_seconds:
                self._flush_buffer()

        except Exception as e:
            logger.error(f"Failed to record step {result.step_id}: {e}")

    def _flush_buffer(self) -> None:
        """Flush buffered step results to MongoDB."""
        if not self._buffer:
            return

        # Copy buffer and clear
        steps = list(self._buffer)
        self._buffer.clear()
        self._last_flush = time.time()

        try:
            # Group steps by task (assuming step_id format: task_id:step_number)
            from collections import defaultdict
            task_steps = defaultdict(list)

            for step in steps:
                # Extract task_id from step_id (simple split on first colon)
                step_id = step["step_id"]
                if ":" in step_id:
                    task_id = step_id.split(":", 1)[0]
                else:
                    # Fallback: use step_id as task_id
                    task_id = step_id

                task_steps[task_id].append(step)

            # Write to MongoDB (one update per task)
            for task_id, task_step_list in task_steps.items():
                # Aggregate token/cost deltas
                total_token_delta = sum(s["token_count_delta"] for s in task_step_list)
                total_cost_delta = sum(s["cost_usd_delta"] for s in task_step_list)

                self._progress.update_one(
                    {"_id": task_id},
                    {
                        "$push": {"steps": {"$each": task_step_list}},
                        "$inc": {
                            "step_count": len(task_step_list),
                            "total_tokens": total_token_delta,
                            "total_cost_usd": total_cost_delta
                        },
                        "$set": {"updated_at": datetime.now(timezone.utc)}
                    },
                    upsert=True
                )

        except Exception as e:
            logger.error(f"Failed to flush progress buffer: {e}")

    def flush_all(self) -> None:
        """Force immediate flush of buffer (for shutdown)."""
        self._flush_buffer()
