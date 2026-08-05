"""
Task ledger interface.

Defines protocol for task plan storage and updates.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from emitters.source_health_registry import SourceHealthRegistry

# Import pymongo at module level for mockability
try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:
    MongoClient = None
    PyMongoError = Exception

logger = logging.getLogger(__name__)


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


class MongoTaskLedger:
    """
    MongoDB-backed task ledger with goal enrichment and dependency resolution.

    Provides task plan retrieval with goal metadata enrichment and dependency
    status checking. Gracefully degrades to NoOp behavior when MongoDB unavailable.
    """

    def __init__(self, mongo_uri: str, database: str = "fingpt_agents"):
        """
        Initialize MongoDB task ledger.

        Args:
            mongo_uri: MongoDB connection URI
            database: Database name (default: fingpt_agents)
        """
        self._mongodb_available = False
        self._client = None
        self._db = None
        self._tasks = None
        self._goals = None

        if MongoClient is None:
            logger.warning(
                "pymongo not available. MongoTaskLedger will behave like NoOpTaskLedger. "
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
            self._tasks = self._db["agent_tasks"]
            self._goals = self._db["agent_goals"]
            # Capability flag only (pymongo importable + client constructed).
            # NOT a health claim: MongoClient() is lazy and never contacts the
            # server here, so we must NOT report("mongo", available=True) off
            # this constructor — that would clobber a correct op-time
            # available=False under the shared last-writer-wins source_id
            # (CR-01). Health is reported at op time only.
            self._mongodb_available = True
            logger.info(f"MongoTaskLedger initialized with database: {database}")
        except Exception as e:
            # Match this module's existing degrade-to-NoOp idiom; emit the
            # health signal alongside the warning (D-07).
            SourceHealthRegistry.get_shared_instance().report(
                "mongo", available=False, failure_reason=type(e).__name__
            )
            logger.warning(
                f"MongoDB connection failed: {e}. "
                "MongoTaskLedger will behave like NoOpTaskLedger."
            )

    async def get_plan(self, task_id: str) -> dict:
        """
        Retrieve task plan enriched with goal metadata and dependency resolution.

        Args:
            task_id: Task identifier

        Returns:
            Enriched task plan with keys:
            - task: Task document
            - goal: Goal document (if task has goal_id)
            - dependencies: List of dependency statuses (from blocked_by tasks)
            - brain_context: Brain-specific context if available
        """
        if not self._mongodb_available:
            return {}

        try:
            # Fetch task document
            task_doc = self._tasks.find_one({"_id": task_id})
            # A real op reached Mongo and returned — report health at op time.
            SourceHealthRegistry.get_shared_instance().report("mongo", available=True)
            if not task_doc:
                logger.warning(f"Task not found: {task_id}")
                return {}

            result = {"task": task_doc}

            # Enrich with goal metadata
            goal_id = task_doc.get("goal_id")
            if goal_id:
                goal_doc = self._goals.find_one({"_id": goal_id})
                if goal_doc:
                    result["goal"] = goal_doc
                else:
                    logger.warning(f"Goal not found: {goal_id} for task {task_id}")

            # Resolve dependencies
            blocked_by = task_doc.get("blocked_by", [])
            if blocked_by:
                dependencies = []
                for dep_task_id in blocked_by:
                    dep_task = self._tasks.find_one(
                        {"_id": dep_task_id},
                        {"status": 1}
                    )
                    if dep_task:
                        dependencies.append({
                            "task_id": dep_task_id,
                            "status": dep_task.get("status", "UNKNOWN")
                        })
                    else:
                        dependencies.append({
                            "task_id": dep_task_id,
                            "status": "NOT_FOUND"
                        })
                result["dependencies"] = dependencies
            else:
                result["dependencies"] = []

            # Include brain_context if available
            if "brain_context" in task_doc:
                result["brain_context"] = task_doc["brain_context"]

            return result

        except Exception as e:
            SourceHealthRegistry.get_shared_instance().report(
                "mongo", available=False, failure_reason=type(e).__name__
            )
            logger.error(f"Failed to get plan for task {task_id}: {e}")
            return {}

    async def update(self, task_id: str, data: dict) -> None:
        """
        Atomically update task with monotonic version check.

        Uses optimistic concurrency control. Retries once on version mismatch.

        Args:
            task_id: Task identifier
            data: Update data
        """
        if not self._mongodb_available:
            return

        try:
            # First attempt
            success = self._attempt_update(task_id, data)
            # A real op reached Mongo — report health at op time.
            SourceHealthRegistry.get_shared_instance().report("mongo", available=True)
            if success:
                return

            # Retry once on version mismatch
            logger.warning(f"Version mismatch on task {task_id}, retrying once")
            success = self._attempt_update(task_id, data)
            if not success:
                logger.error(f"Failed to update task {task_id} after retry (version conflict)")

        except Exception as e:
            SourceHealthRegistry.get_shared_instance().report(
                "mongo", available=False, failure_reason=type(e).__name__
            )
            logger.error(f"Failed to update task {task_id}: {e}")

    def _attempt_update(self, task_id: str, data: dict) -> bool:
        """
        Attempt atomic update with version check.

        Args:
            task_id: Task identifier
            data: Update data

        Returns:
            True if update succeeded, False if version mismatch
        """
        # Fetch current version
        current_doc = self._tasks.find_one({"_id": task_id}, {"version": 1})
        if not current_doc:
            logger.warning(f"Task not found for update: {task_id}")
            return False

        current_version = current_doc.get("version", 0)

        # Atomic update with version check
        result = self._tasks.update_one(
            {"_id": task_id, "version": current_version},
            {
                "$set": {**data, "updated_at": datetime.now(timezone.utc)},
                "$inc": {"version": 1}
            }
        )

        return result.matched_count > 0
