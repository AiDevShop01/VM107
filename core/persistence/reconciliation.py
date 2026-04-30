"""
Redis-MongoDB drift detection and healing.

Provides:
- Task queue drift detection (MongoDB vs Redis ZSET)
- Brain state drift detection (version mismatch)
- Automatic healing by syncing from MongoDB (authoritative)
- Metrics reporting (healed tasks, removed stale, duration)
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Dict, Set

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    """Results of reconciliation run."""
    healed_tasks: int
    removed_stale: int
    brain_state_healed: bool
    duration_ms: int


class ReconciliationJob:
    """
    Redis-MongoDB drift detection and healing job.

    Compares Redis queue vs MongoDB agent_tasks (status=queued), detects
    missing/extra/score-drift entries, heals by syncing from MongoDB.
    """

    def __init__(
        self,
        mongo_db,
        redis_client,
        queue_key: str = "queue:runnable",
        brain_cache_ttl: int = 300
    ):
        """
        Initialize reconciliation job.

        Args:
            mongo_db: MongoDB database instance
            redis_client: Redis client instance
            queue_key: Redis ZSET queue key
            brain_cache_ttl: Brain state cache TTL in seconds
        """
        self.mongo_db = mongo_db
        self.redis = redis_client
        self.queue_key = queue_key
        self.brain_cache_ttl = brain_cache_ttl

    def run(self, score_drift_threshold: float = 1.0) -> ReconciliationResult:
        """
        Run reconciliation check and heal drift.

        Args:
            score_drift_threshold: Score difference to trigger update

        Returns:
            ReconciliationResult with metrics
        """
        start_time = time.time()

        healed_tasks = 0
        removed_stale = 0

        # 1. Reconcile task queue
        healed, removed = self._reconcile_task_queue(score_drift_threshold)
        healed_tasks += healed
        removed_stale += removed

        # 2. Reconcile brain state
        brain_healed = self._reconcile_brain_state()

        duration_ms = max(1, int((time.time() - start_time) * 1000))

        return ReconciliationResult(
            healed_tasks=healed_tasks,
            removed_stale=removed_stale,
            brain_state_healed=brain_healed,
            duration_ms=duration_ms
        )

    def _reconcile_task_queue(self, score_drift_threshold: float) -> tuple[int, int]:
        """
        Reconcile task queue between MongoDB and Redis.

        Returns:
            (healed_count, removed_count)
        """
        healed = 0
        removed = 0

        # Fetch queued tasks from MongoDB (authoritative)
        mongo_tasks = self.mongo_db.agent_tasks.find({"status": "queued"})
        mongo_map: Dict[str, float] = {
            task["_id"]: task.get("score", 0.0)
            for task in mongo_tasks
        }

        # Fetch tasks from Redis queue
        redis_tasks = self.redis.zrange(
            self.queue_key,
            0, -1,
            withscores=True
        )
        redis_map: Dict[str, float] = {
            (member.decode() if isinstance(member, bytes) else member): score
            for member, score in redis_tasks
        }

        # Find tasks in Mongo but not Redis (re-enqueue)
        mongo_ids = set(mongo_map.keys())
        redis_ids = set(redis_map.keys())

        missing_in_redis = mongo_ids - redis_ids
        if missing_in_redis:
            logger.info(f"Re-enqueueing {len(missing_in_redis)} missing tasks")
            for task_id in missing_in_redis:
                self.redis.zadd(self.queue_key, {task_id: mongo_map[task_id]})
                healed += 1

        # Find tasks in Redis but not Mongo (remove stale)
        stale_in_redis = redis_ids - mongo_ids
        if stale_in_redis:
            logger.info(f"Removing {len(stale_in_redis)} stale tasks from Redis")
            for task_id in stale_in_redis:
                self.redis.zrem(self.queue_key, task_id)
                removed += 1

        # Check score drift for tasks in both
        common_tasks = mongo_ids & redis_ids
        for task_id in common_tasks:
            mongo_score = mongo_map[task_id]
            redis_score = redis_map[task_id]
            drift = abs(mongo_score - redis_score)

            if drift > score_drift_threshold:
                logger.info(f"Updating score for {task_id}: {redis_score} -> {mongo_score} (drift={drift})")
                self.redis.zadd(self.queue_key, {task_id: mongo_score})
                healed += 1

        return (healed, removed)

    def _reconcile_brain_state(self) -> bool:
        """
        Reconcile brain state between MongoDB and Redis.

        Returns:
            True if healed, False if no drift
        """
        # Fetch brain state from MongoDB (authoritative)
        mongo_brain = self.mongo_db.brain_state.find_one({"_id": "brain:global"})
        if not mongo_brain:
            return False

        # Fetch brain state from Redis
        redis_brain_raw = self.redis.get("brain:global")
        redis_brain = None
        if redis_brain_raw:
            try:
                redis_brain = json.loads(redis_brain_raw)
            except json.JSONDecodeError:
                logger.warning("Failed to decode Redis brain_state")

        # Check version drift
        mongo_version = mongo_brain.get("version", 0)
        redis_version = redis_brain.get("version", 0) if redis_brain else 0

        if mongo_version != redis_version or redis_brain is None:
            logger.info(f"Healing brain_state: Redis version {redis_version} -> MongoDB version {mongo_version}")
            self.redis.setex(
                "brain:global",
                self.brain_cache_ttl,
                json.dumps(mongo_brain, default=str)
            )
            return True

        return False
