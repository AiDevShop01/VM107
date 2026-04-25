"""
Budget tracking with MongoDB persistence and in-memory fallback.

Provides BudgetTrackerInterface protocol with two implementations:
- InMemoryBudgetTracker: Simple dict-based (for testing)
- MongoBudgetTracker: MongoDB-backed with atomic $inc and caching
"""
from typing import Protocol, runtime_checkable
from datetime import datetime, timezone
import threading

# Import pymongo at module level for mockability
try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None


@runtime_checkable
class BudgetTrackerInterface(Protocol):
    """Protocol for budget tracking implementations."""

    def add_spend(self, agent_name: str, cost_usd: float) -> None:
        """Add spend to daily budget (atomic operation)."""
        ...

    def get_daily_total(self) -> float:
        """Get total daily spend across all agents."""
        ...

    def get_agent_spend(self, agent_name: str) -> float:
        """Get daily spend for a specific agent."""
        ...


class InMemoryBudgetTracker:
    """In-memory budget tracker for testing."""

    def __init__(self):
        """Initialize in-memory budget tracker."""
        # Structure: {date_str: {total_spend: float, agents: {agent_name: float}}}
        self._data: dict[str, dict] = {}

    def add_spend(self, agent_name: str, cost_usd: float) -> None:
        """Add spend to daily budget."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if today not in self._data:
            self._data[today] = {"total_spend": 0.0, "agents": {}}

        self._data[today]["total_spend"] += cost_usd

        if agent_name not in self._data[today]["agents"]:
            self._data[today]["agents"][agent_name] = 0.0

        self._data[today]["agents"][agent_name] += cost_usd

    def get_daily_total(self) -> float:
        """Get total daily spend across all agents."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if today not in self._data:
            return 0.0

        return self._data[today]["total_spend"]

    def get_agent_spend(self, agent_name: str) -> float:
        """Get daily spend for a specific agent."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if today not in self._data:
            return 0.0

        return self._data[today]["agents"].get(agent_name, 0.0)


class MongoBudgetTracker:
    """MongoDB-backed budget tracker with atomic increments and caching."""

    def __init__(self, mongo_uri: str, database: str = "agent_zero"):
        """
        Initialize MongoDB budget tracker.

        Args:
            mongo_uri: MongoDB connection URI
            database: Database name (default: agent_zero)
        """
        if MongoClient is None:
            raise ImportError(
                "pymongo is required for MongoBudgetTracker. "
                "Install with: pip install pymongo"
            )

        self._client = MongoClient(mongo_uri, retryWrites=True, w="majority")
        self._db = self._client[database]
        self._collection = self._db["budget_usage"]

        # Thread-local cache for daily total (reduce MongoDB reads)
        self._local = threading.local()
        self._cache_ttl_seconds = 60  # Refresh every 60s

    def add_spend(self, agent_name: str, cost_usd: float) -> None:
        """
        Add spend atomically using MongoDB $inc.

        Safe for concurrent multi-agent updates.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Atomic increment (safe for concurrent updates)
        self._collection.update_one(
            {"_id": today},
            {
                "$inc": {
                    "total_spend": cost_usd,
                    f"agents.{agent_name}": cost_usd
                },
                "$set": {"updated_at": datetime.now(timezone.utc)}
            },
            upsert=True  # Create document if first spend of the day
        )

        # Invalidate cache
        if hasattr(self._local, "cached_total"):
            delattr(self._local, "cached_total")
        if hasattr(self._local, "cache_time"):
            delattr(self._local, "cache_time")

    def get_daily_total(self) -> float:
        """Get total daily spend with in-memory caching."""
        now = datetime.now(timezone.utc)

        # Check cache
        if hasattr(self._local, "cached_total") and hasattr(self._local, "cache_time"):
            cache_age = (now - self._local.cache_time).total_seconds()
            if cache_age < self._cache_ttl_seconds:
                return self._local.cached_total

        # Fetch from MongoDB
        today = now.strftime("%Y-%m-%d")
        doc = self._collection.find_one({"_id": today})
        total = doc["total_spend"] if doc else 0.0

        # Update cache
        self._local.cached_total = total
        self._local.cache_time = now

        return total

    def get_agent_spend(self, agent_name: str) -> float:
        """Get daily spend for a specific agent."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        doc = self._collection.find_one({"_id": today})

        if not doc:
            return 0.0

        return doc.get("agents", {}).get(agent_name, 0.0)
