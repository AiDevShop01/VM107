"""
Redis ZSET priority queue for scheduler.

Provides:
- O(log N) enqueue/dequeue with score-based priority
- Atomic batch dequeue (ZPOPMAX)
- Score updates and removals
- Peek top N without removing
- O(1) length check
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class SchedulerDegradedError(Exception):
    """Raised when Redis unavailable - scheduler must degrade."""
    pass


class RedisPriorityQueue:
    """
    Redis ZSET-based priority queue for task scheduling.

    Uses Redis sorted set (ZSET) for O(log N) priority operations.
    Higher scores = higher priority (ZPOPMAX returns highest first).
    """

    def __init__(self, redis_client, queue_key: str = "queue:runnable"):
        """
        Initialize priority queue.

        Args:
            redis_client: Redis client instance
            queue_key: Redis ZSET key name
        """
        self.redis = redis_client
        self.queue_key = queue_key

    def enqueue(self, task_id: str, score: float) -> None:
        """
        Add task to queue with priority score.

        Args:
            task_id: Task identifier
            score: Priority score (higher = higher priority)

        Raises:
            SchedulerDegradedError: Redis connection failed
        """
        try:
            self.redis.zadd(self.queue_key, {task_id: score})
        except Exception as e:
            logger.error(f"Redis enqueue failed: {e}")
            raise SchedulerDegradedError(
                f"Priority queue degraded: {e}"
            ) from e

    def dequeue_batch(self, batch_size: int = 5) -> List[Tuple[str, float]]:
        """
        Atomically pop top N tasks by score.

        Args:
            batch_size: Number of tasks to dequeue

        Returns:
            List of (task_id, score) tuples, highest score first

        Raises:
            SchedulerDegradedError: Redis connection failed
        """
        try:
            results = self.redis.zpopmax(self.queue_key, count=batch_size)

            # Convert bytes to strings
            return [
                (member.decode() if isinstance(member, bytes) else member, score)
                for member, score in results
            ]
        except Exception as e:
            logger.error(f"Redis dequeue failed: {e}")
            raise SchedulerDegradedError(
                f"Priority queue degraded: {e}"
            ) from e

    def update_score(self, task_id: str, new_score: float) -> None:
        """
        Update score for existing task.

        Args:
            task_id: Task identifier
            new_score: New priority score

        Raises:
            SchedulerDegradedError: Redis connection failed
        """
        try:
            # ZADD overwrites score for existing member
            self.redis.zadd(self.queue_key, {task_id: new_score})
        except Exception as e:
            logger.error(f"Redis update_score failed: {e}")
            raise SchedulerDegradedError(
                f"Priority queue degraded: {e}"
            ) from e

    def remove(self, task_id: str) -> None:
        """
        Remove task from queue.

        Args:
            task_id: Task identifier

        Raises:
            SchedulerDegradedError: Redis connection failed
        """
        try:
            self.redis.zrem(self.queue_key, task_id)
        except Exception as e:
            logger.error(f"Redis remove failed: {e}")
            raise SchedulerDegradedError(
                f"Priority queue degraded: {e}"
            ) from e

    def peek_top(self, n: int = 10) -> List[Tuple[str, float]]:
        """
        Get top N tasks without removing them.

        Args:
            n: Number of tasks to peek

        Returns:
            List of (task_id, score) tuples, highest score first

        Raises:
            SchedulerDegradedError: Redis connection failed
        """
        try:
            results = self.redis.zrevrange(
                self.queue_key,
                0, n - 1,
                withscores=True
            )

            # Convert bytes to strings
            return [
                (member.decode() if isinstance(member, bytes) else member, score)
                for member, score in results
            ]
        except Exception as e:
            logger.error(f"Redis peek_top failed: {e}")
            raise SchedulerDegradedError(
                f"Priority queue degraded: {e}"
            ) from e

    def length(self) -> int:
        """
        Get queue size.

        Returns:
            Number of tasks in queue

        Raises:
            SchedulerDegradedError: Redis connection failed
        """
        try:
            return self.redis.zcard(self.queue_key)
        except Exception as e:
            logger.error(f"Redis length failed: {e}")
            raise SchedulerDegradedError(
                f"Priority queue degraded: {e}"
            ) from e
