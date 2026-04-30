"""
Tests for RedisPriorityQueue ZSET operations.

TDD RED phase: Define expected behavior before implementation.
"""

import pytest
from unittest.mock import Mock

from core.persistence.redis_queue import RedisPriorityQueue, SchedulerDegradedError


class TestRedisPriorityQueue:
    """Test Redis ZSET priority queue for scheduler."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        mock = Mock()
        mock.zadd = Mock(return_value=1)
        mock.zpopmax = Mock(return_value=[])
        mock.zrem = Mock(return_value=1)
        mock.zrevrange = Mock(return_value=[])
        mock.zcard = Mock(return_value=0)
        return mock

    @pytest.fixture
    def queue(self, mock_redis):
        """Create RedisPriorityQueue instance."""
        return RedisPriorityQueue(
            redis_client=mock_redis,
            queue_key="queue:runnable"
        )

    def test_enqueue(self, queue, mock_redis):
        """enqueue() should add task to ZSET with score."""
        queue.enqueue("task-123", score=10.5)

        mock_redis.zadd.assert_called_once_with(
            "queue:runnable",
            {"task-123": 10.5}
        )

    def test_dequeue_batch(self, queue, mock_redis):
        """dequeue_batch() should atomically pop top N by score."""
        # Mock ZPOPMAX returning [(member, score), ...]
        mock_redis.zpopmax.return_value = [
            (b"task-456", 15.0),
            (b"task-123", 10.5),
            (b"task-789", 8.0)
        ]

        result = queue.dequeue_batch(batch_size=3)

        mock_redis.zpopmax.assert_called_once_with("queue:runnable", count=3)
        assert result == [
            ("task-456", 15.0),
            ("task-123", 10.5),
            ("task-789", 8.0)
        ]

    def test_dequeue_batch_empty(self, queue, mock_redis):
        """dequeue_batch() should return empty list when queue empty."""
        mock_redis.zpopmax.return_value = []

        result = queue.dequeue_batch(batch_size=5)

        assert result == []

    def test_update_score(self, queue, mock_redis):
        """update_score() should update existing member score."""
        queue.update_score("task-123", new_score=20.0)

        # ZADD overwrites score for existing member
        mock_redis.zadd.assert_called_once_with(
            "queue:runnable",
            {"task-123": 20.0}
        )

    def test_remove(self, queue, mock_redis):
        """remove() should remove task from queue."""
        queue.remove("task-456")

        mock_redis.zrem.assert_called_once_with("queue:runnable", "task-456")

    def test_peek_top(self, queue, mock_redis):
        """peek_top() should return top N without removing."""
        mock_redis.zrevrange.return_value = [
            (b"task-789", 25.0),
            (b"task-456", 15.0),
            (b"task-123", 10.5)
        ]

        result = queue.peek_top(n=3)

        mock_redis.zrevrange.assert_called_once_with(
            "queue:runnable",
            0, 2,  # n-1
            withscores=True
        )
        assert result == [
            ("task-789", 25.0),
            ("task-456", 15.0),
            ("task-123", 10.5)
        ]

    def test_length(self, queue, mock_redis):
        """length() should return queue size O(1)."""
        mock_redis.zcard.return_value = 42

        result = queue.length()

        mock_redis.zcard.assert_called_once_with("queue:runnable")
        assert result == 42

    def test_redis_connection_error_raises(self, queue, mock_redis):
        """Redis ConnectionError should raise SchedulerDegradedError."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        mock_redis.zadd.side_effect = RedisConnectionError("Connection refused")

        with pytest.raises(SchedulerDegradedError) as exc_info:
            queue.enqueue("task-123", score=10.0)

        assert "degraded" in str(exc_info.value).lower()

    def test_default_queue_key(self, mock_redis):
        """Should use default queue_key if not specified."""
        queue = RedisPriorityQueue(redis_client=mock_redis)

        queue.enqueue("task-1", score=5.0)

        # Should use default key
        mock_redis.zadd.assert_called_once()
        call_args = mock_redis.zadd.call_args
        assert call_args[0][0] == "queue:runnable"
