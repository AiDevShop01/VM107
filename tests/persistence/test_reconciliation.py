"""
Tests for ReconciliationJob drift detection and healing.

TDD RED phase: Define expected behavior before implementation.
"""

import pytest
from unittest.mock import Mock
from dataclasses import dataclass

from core.persistence.reconciliation import ReconciliationJob, ReconciliationResult


class TestReconciliationJob:
    """Test Redis-MongoDB drift detection and healing."""

    @pytest.fixture
    def mock_mongo_db(self):
        """Mock MongoDB database."""
        mock_db = Mock()

        # Mock agent_tasks collection
        mock_tasks = Mock()
        mock_tasks.find.return_value = []
        mock_db.agent_tasks = mock_tasks

        # Mock brain_state collection
        mock_brain = Mock()
        mock_brain.find_one.return_value = None
        mock_db.brain_state = mock_brain

        return mock_db

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        mock = Mock()
        mock.zrange = Mock(return_value=[])
        mock.zadd = Mock()
        mock.zrem = Mock()
        mock.get = Mock(return_value=None)
        mock.setex = Mock()
        return mock

    @pytest.fixture
    def reconciliation(self, mock_mongo_db, mock_redis):
        """Create ReconciliationJob instance."""
        return ReconciliationJob(
            mongo_db=mock_mongo_db,
            redis_client=mock_redis,
            queue_key="queue:runnable"
        )

    def test_no_drift(self, reconciliation, mock_mongo_db, mock_redis):
        """Should report no changes when Redis and MongoDB in sync."""
        # MongoDB has 2 queued tasks
        mock_mongo_db.agent_tasks.find.return_value = [
            {"_id": "task-1", "status": "queued", "score": 10.0},
            {"_id": "task-2", "status": "queued", "score": 5.0}
        ]

        # Redis has same 2 tasks
        mock_redis.zrange.return_value = [
            (b"task-1", 10.0),
            (b"task-2", 5.0)
        ]

        # Brain state matches
        mock_mongo_db.brain_state.find_one.return_value = {
            "_id": "brain:global",
            "version": 42
        }
        mock_redis.get.return_value = b'{"_id": "brain:global", "version": 42}'

        result = reconciliation.run()

        assert result.healed_tasks == 0
        assert result.removed_stale == 0
        assert result.brain_state_healed is False

    def test_task_missing_in_redis(self, reconciliation, mock_mongo_db, mock_redis):
        """Should re-enqueue tasks in MongoDB but not Redis."""
        # MongoDB has 3 queued tasks
        mock_mongo_db.agent_tasks.find.return_value = [
            {"_id": "task-1", "status": "queued", "score": 10.0},
            {"_id": "task-2", "status": "queued", "score": 5.0},
            {"_id": "task-3", "status": "queued", "score": 8.0}
        ]

        # Redis only has 2 tasks (missing task-3)
        mock_redis.zrange.return_value = [
            (b"task-1", 10.0),
            (b"task-2", 5.0)
        ]

        result = reconciliation.run()

        # Should add missing task to Redis
        mock_redis.zadd.assert_called_once()
        zadd_args = mock_redis.zadd.call_args
        assert zadd_args[0][0] == "queue:runnable"
        assert zadd_args[0][1] == {"task-3": 8.0}

        assert result.healed_tasks == 1
        assert result.removed_stale == 0

    def test_task_in_redis_not_mongo(self, reconciliation, mock_mongo_db, mock_redis):
        """Should remove tasks in Redis but not MongoDB."""
        # MongoDB has 1 queued task
        mock_mongo_db.agent_tasks.find.return_value = [
            {"_id": "task-1", "status": "queued", "score": 10.0}
        ]

        # Redis has 2 tasks (task-stale is extra)
        mock_redis.zrange.return_value = [
            (b"task-1", 10.0),
            (b"task-stale", 99.0)
        ]

        result = reconciliation.run()

        # Should remove stale task from Redis
        mock_redis.zrem.assert_called_once_with("queue:runnable", "task-stale")

        assert result.healed_tasks == 0
        assert result.removed_stale == 1

    def test_score_drift(self, reconciliation, mock_mongo_db, mock_redis):
        """Should update score when drift exceeds threshold."""
        # MongoDB has task with score 10.0
        mock_mongo_db.agent_tasks.find.return_value = [
            {"_id": "task-1", "status": "queued", "score": 10.0}
        ]

        # Redis has same task with drifted score (5.5, drift = 4.5)
        mock_redis.zrange.return_value = [
            (b"task-1", 5.5)
        ]

        result = reconciliation.run(score_drift_threshold=1.0)

        # Should update score in Redis
        mock_redis.zadd.assert_called_once()
        zadd_args = mock_redis.zadd.call_args
        assert zadd_args[0][1] == {"task-1": 10.0}

        assert result.healed_tasks == 1

    def test_brain_state_drift(self, reconciliation, mock_mongo_db, mock_redis):
        """Should heal brain_state version drift."""
        # No task drift
        mock_mongo_db.agent_tasks.find.return_value = []
        mock_redis.zrange.return_value = []

        # MongoDB brain_state version 50
        mock_mongo_db.brain_state.find_one.return_value = {
            "_id": "brain:global",
            "version": 50,
            "mode": "exploration"
        }

        # Redis brain_state version 45 (drifted)
        mock_redis.get.return_value = b'{"_id": "brain:global", "version": 45, "mode": "exploitation"}'

        result = reconciliation.run()

        # Should update Redis brain_state
        mock_redis.setex.assert_called_once()
        setex_args = mock_redis.setex.call_args
        assert setex_args[0][0] == "brain:global"
        assert result.brain_state_healed is True

    def test_brain_state_missing_in_redis(self, reconciliation, mock_mongo_db, mock_redis):
        """Should populate brain_state in Redis if missing."""
        mock_mongo_db.agent_tasks.find.return_value = []
        mock_redis.zrange.return_value = []

        # MongoDB has brain_state
        mock_mongo_db.brain_state.find_one.return_value = {
            "_id": "brain:global",
            "version": 1,
            "mode": "exploration"
        }

        # Redis missing brain_state
        mock_redis.get.return_value = None

        result = reconciliation.run()

        # Should populate Redis
        mock_redis.setex.assert_called_once()
        assert result.brain_state_healed is True

    def test_duration_tracked(self, reconciliation, mock_mongo_db, mock_redis):
        """Should track execution duration in milliseconds."""
        mock_mongo_db.agent_tasks.find.return_value = []
        mock_redis.zrange.return_value = []

        result = reconciliation.run()

        assert result.duration_ms > 0
        assert isinstance(result.duration_ms, int)

    def test_reconciliation_result_structure(self):
        """ReconciliationResult should have all required fields."""
        result = ReconciliationResult(
            healed_tasks=5,
            removed_stale=2,
            brain_state_healed=True,
            duration_ms=123
        )

        assert result.healed_tasks == 5
        assert result.removed_stale == 2
        assert result.brain_state_healed is True
        assert result.duration_ms == 123
