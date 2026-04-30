"""
Tests for MongoCachedCollection write-through cache.

TDD RED phase: Define expected behavior before implementation.
"""

import json
import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime

from core.persistence.mongo_cache import MongoCachedCollection


class TestMongoCachedCollection:
    """Test write-through MongoDB+Redis cache with monotonic versioning."""

    @pytest.fixture
    def mock_mongo_collection(self):
        """Mock PyMongo collection."""
        mock = Mock()
        mock.find_one = Mock(return_value=None)
        mock.update_one = Mock()
        return mock

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        mock = Mock()
        mock.get = Mock(return_value=None)
        mock.setex = Mock()
        mock.publish = Mock()
        return mock

    @pytest.fixture
    def cache(self, mock_mongo_collection, mock_redis):
        """Create MongoCachedCollection instance."""
        return MongoCachedCollection(
            mongo_collection=mock_mongo_collection,
            redis_client=mock_redis,
            cache_prefix="test",
            ttl=60
        )

    def test_get_cache_hit(self, cache, mock_redis):
        """get() should return cached value without MongoDB call."""
        cached_doc = {"_id": "task-123", "status": "running", "version": 5}
        mock_redis.get.return_value = json.dumps(cached_doc, default=str).encode()

        result = cache.get("task-123")

        assert result == cached_doc
        mock_redis.get.assert_called_once_with("test:task-123")
        cache.collection.find_one.assert_not_called()

    def test_get_cache_miss_populates(self, cache, mock_mongo_collection, mock_redis):
        """get() should fall back to MongoDB and populate cache on miss."""
        mock_redis.get.return_value = None
        mongo_doc = {"_id": "task-456", "status": "queued", "version": 1}
        mock_mongo_collection.find_one.return_value = mongo_doc

        result = cache.get("task-456")

        assert result == mongo_doc
        mock_mongo_collection.find_one.assert_called_once_with({"_id": "task-456"})
        # Should cache the result
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "test:task-456"
        assert args[0][1] == 60

    def test_get_not_found(self, cache, mock_mongo_collection, mock_redis):
        """get() should return None if document not found in both stores."""
        mock_redis.get.return_value = None
        mock_mongo_collection.find_one.return_value = None

        result = cache.get("task-999")

        assert result is None

    def test_update_writes_through(self, cache, mock_mongo_collection, mock_redis):
        """update() should write to MongoDB first, then mirror to Redis."""
        updated_doc = {"_id": "task-123", "status": "completed", "version": 6}

        # MongoDB update succeeds and returns updated doc
        mock_result = Mock()
        mock_result.matched_count = 1
        mock_mongo_collection.update_one.return_value = mock_result
        mock_mongo_collection.find_one.return_value = updated_doc

        cache.update("task-123", {"status": "completed"}, current_version=5)

        # MongoDB write with version check
        mock_mongo_collection.update_one.assert_called_once()
        update_call = mock_mongo_collection.update_one.call_args
        assert update_call[0][0] == {"_id": "task-123", "version": 5}
        assert "$set" in update_call[0][1]
        assert "$inc" in update_call[0][1]
        assert update_call[0][1]["$inc"]["version"] == 1

        # Redis cache updated
        mock_redis.setex.assert_called_once()

        # Pub/sub notification
        mock_redis.publish.assert_called_once()
        pub_args = mock_redis.publish.call_args
        assert pub_args[0][0] == "test:updates"

    def test_update_version_mismatch(self, cache, mock_mongo_collection):
        """update() should raise ConcurrentModificationError on version mismatch."""
        mock_result = Mock()
        mock_result.matched_count = 0  # Version mismatch
        mock_mongo_collection.update_one.return_value = mock_result

        from core.persistence.mongo_cache import ConcurrentModificationError

        with pytest.raises(ConcurrentModificationError) as exc_info:
            cache.update("task-123", {"status": "completed"}, current_version=5)

        assert "version mismatch" in str(exc_info.value).lower()

    def test_redis_unavailable_graceful_degradation(self, cache, mock_mongo_collection, mock_redis):
        """Should degrade gracefully to MongoDB-only when Redis unavailable."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        # Redis operations fail
        mock_redis.get.side_effect = RedisConnectionError("Connection refused")
        mock_redis.setex.side_effect = RedisConnectionError("Connection refused")
        mock_redis.publish.side_effect = RedisConnectionError("Connection refused")

        # MongoDB still works
        mongo_doc = {"_id": "task-789", "status": "running", "version": 2}
        mock_mongo_collection.find_one.return_value = mongo_doc

        # get() should still work
        result = cache.get("task-789")
        assert result == mongo_doc

        # update() should still work
        updated_doc = {"_id": "task-789", "status": "completed", "version": 3}
        mock_result = Mock()
        mock_result.matched_count = 1
        mock_mongo_collection.update_one.return_value = mock_result
        mock_mongo_collection.find_one.return_value = updated_doc

        cache.update("task-789", {"status": "completed"}, current_version=2)
        # Should not raise, just log warning

    def test_datetime_serialization(self, cache, mock_mongo_collection, mock_redis):
        """Should handle datetime serialization with json.dumps(default=str)."""
        now = datetime.utcnow()
        doc_with_datetime = {
            "_id": "task-dt",
            "created_at": now,
            "version": 1
        }

        mock_redis.get.return_value = None
        mock_mongo_collection.find_one.return_value = doc_with_datetime

        result = cache.get("task-dt")

        assert result == doc_with_datetime
        # Verify Redis setex was called with serialized datetime
        mock_redis.setex.assert_called_once()
        cached_value = mock_redis.setex.call_args[0][2]
        assert isinstance(cached_value, (str, bytes))
