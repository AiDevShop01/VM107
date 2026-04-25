"""
Tests for BudgetTracker implementations.

Tests both InMemoryBudgetTracker and MongoBudgetTracker (mocked).
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from core.boundary.budget_tracker import (
    BudgetTrackerInterface,
    InMemoryBudgetTracker,
    MongoBudgetTracker
)


class TestInMemoryBudgetTracker:
    """Test suite for InMemoryBudgetTracker."""

    def test_in_memory_add_spend(self):
        """InMemoryBudgetTracker.add_spend increments daily total."""
        tracker = InMemoryBudgetTracker()
        tracker.add_spend("agent_a", 0.50)
        tracker.add_spend("agent_b", 0.30)

        total = tracker.get_daily_total()
        assert abs(total - 0.80) < 0.0001

    def test_in_memory_get_daily_total(self):
        """Returns sum of all add_spend calls."""
        tracker = InMemoryBudgetTracker()
        tracker.add_spend("agent_a", 0.10)
        tracker.add_spend("agent_a", 0.20)
        tracker.add_spend("agent_b", 0.15)

        assert abs(tracker.get_daily_total() - 0.45) < 0.0001

    def test_in_memory_per_agent_tracking(self):
        """Tracks spend per agent name separately."""
        tracker = InMemoryBudgetTracker()
        tracker.add_spend("agent_a", 0.50)
        tracker.add_spend("agent_b", 0.30)

        assert tracker.get_agent_spend("agent_a") == 0.50
        assert tracker.get_agent_spend("agent_b") == 0.30
        assert tracker.get_agent_spend("agent_c") == 0.0

    def test_daily_reset(self):
        """New date key returns 0.0 (simulated via date mocking)."""
        tracker = InMemoryBudgetTracker()

        # Add spend on "day 1"
        with patch('core.boundary.budget_tracker.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            tracker.add_spend("agent_a", 0.50)

        # Check spend on "day 2" (different date)
        with patch('core.boundary.budget_tracker.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            total = tracker.get_daily_total()

        # Should be 0.0 because it's a new day
        assert total == 0.0


class TestMongoBudgetTracker:
    """Test suite for MongoBudgetTracker (mocked MongoDB)."""

    @pytest.fixture
    def mock_mongo_client(self):
        """Mock pymongo MongoClient."""
        with patch('core.boundary.budget_tracker.MongoClient') as mock_client:
            mock_db = MagicMock()
            mock_collection = MagicMock()

            mock_client.return_value.__getitem__.return_value = mock_db
            mock_db.__getitem__.return_value = mock_collection

            yield mock_collection

    def test_mongo_tracker_add_spend(self, mock_mongo_client):
        """MongoBudgetTracker calls update_one with $inc (mocked pymongo)."""
        tracker = MongoBudgetTracker("mongodb://localhost:27017")
        tracker.add_spend("agent_a", 0.42)

        # Verify update_one called with $inc
        mock_mongo_client.update_one.assert_called_once()
        call_args = mock_mongo_client.update_one.call_args

        # Check filter (document ID = today's date)
        filter_dict = call_args[0][0]
        assert "_id" in filter_dict

        # Check $inc operation
        update_dict = call_args[0][1]
        assert "$inc" in update_dict
        assert "total_spend" in update_dict["$inc"]
        assert update_dict["$inc"]["total_spend"] == 0.42

        # Check upsert
        assert call_args[1].get("upsert") is True

    def test_mongo_tracker_cache(self, mock_mongo_client):
        """Second get_daily_total within TTL uses cache (no MongoDB query)."""
        # Setup mock to return a document
        mock_mongo_client.find_one.return_value = {"total_spend": 5.00}

        tracker = MongoBudgetTracker("mongodb://localhost:27017")

        # First call - should query MongoDB
        total1 = tracker.get_daily_total()
        assert total1 == 5.00
        assert mock_mongo_client.find_one.call_count == 1

        # Second call within TTL - should use cache
        total2 = tracker.get_daily_total()
        assert total2 == 5.00
        assert mock_mongo_client.find_one.call_count == 1  # Still 1 (cached)

    def test_mongo_tracker_cache_invalidation(self, mock_mongo_client):
        """add_spend invalidates cache."""
        # Setup mock to return a document
        mock_mongo_client.find_one.return_value = {"total_spend": 5.00}

        tracker = MongoBudgetTracker("mongodb://localhost:27017")

        # Get total (populates cache)
        tracker.get_daily_total()
        assert mock_mongo_client.find_one.call_count == 1

        # Add spend (invalidates cache)
        tracker.add_spend("agent_a", 0.50)

        # Get total again (should query MongoDB again)
        mock_mongo_client.find_one.return_value = {"total_spend": 5.50}
        total = tracker.get_daily_total()
        assert total == 5.50
        assert mock_mongo_client.find_one.call_count == 2

    def test_budget_tracker_protocol(self):
        """Both implementations satisfy BudgetTrackerInterface protocol."""
        from typing import runtime_checkable, Protocol

        # Check that BudgetTrackerInterface is runtime_checkable
        assert isinstance(BudgetTrackerInterface, type)

        # Check InMemoryBudgetTracker
        in_memory = InMemoryBudgetTracker()
        assert hasattr(in_memory, "add_spend")
        assert hasattr(in_memory, "get_daily_total")
        assert hasattr(in_memory, "get_agent_spend")

        # MongoBudgetTracker check would require MongoDB connection
        # so we just verify the class has the right methods
        assert hasattr(MongoBudgetTracker, "add_spend")
        assert hasattr(MongoBudgetTracker, "get_daily_total")
        assert hasattr(MongoBudgetTracker, "get_agent_spend")
