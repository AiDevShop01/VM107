"""
Budget tracking with MongoDB persistence and in-memory fallback.

Provides BudgetTrackerInterface protocol with two implementations:
- InMemoryBudgetTracker: Simple dict-based (for testing)
- MongoBudgetTracker: MongoDB-backed with atomic $inc and caching
"""
from typing import Protocol, runtime_checkable
from datetime import datetime, timezone
import os
import threading
import time

from emitters.source_health_registry import SourceHealthRegistry

# Import pymongo at module level for mockability
try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:
    MongoClient = None
    PyMongoError = Exception


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

    def __init__(self, mongo_uri: str, database: str = "fingpt_agents"):
        """
        Initialize MongoDB budget tracker.

        Args:
            mongo_uri: MongoDB connection URI
            database: Database name (default: fingpt_agents, Phase 41 migration)

        Note:
            After Phase 41 migration, budget_usage data is stored in fingpt_agents.
            Historical data from Phase 38 (agent_zero) is migrated via migration 002.
            Callers can still pass database="agent_zero" for backward compatibility.
        """
        if MongoClient is None:
            raise ImportError(
                "pymongo is required for MongoBudgetTracker. "
                "Install with: pip install pymongo"
            )

        # serverSelectionTimeoutMS bounds the FIRST op so a down Mongo fast-fails
        # (mirrors orchestrator_factory.py:69; env-driven resilience default per
        # D-05/D-06). MongoClient is lazy — no connect/ping here (D-08 wants
        # fast-fail-then-degrade on first op, not a boot abort).
        self._client = MongoClient(
            mongo_uri,
            retryWrites=True,
            w="majority",
            serverSelectionTimeoutMS=int(os.getenv("A0_MONGO_TIMEOUT_MS", "5000")),
        )
        self._db = self._client[database]
        self._collection = self._db["budget_usage"]

        # Thread-local cache for daily total (reduce MongoDB reads)
        self._local = threading.local()
        self._cache_ttl_seconds = 60  # Refresh every 60s

        # Lazily-held in-memory fallback — the per-LLM-call budget path must
        # NEVER block/raise on a down Mongo (D-08). On a PyMongoError each op
        # degrades to this tracker and emits a `budget_mongo` health signal.
        self._fallback_tracker: "InMemoryBudgetTracker | None" = None

        # WR-02: sticky degrade latch. Without it, a down Mongo costs the full
        # serverSelectionTimeoutMS (~5s) on EVERY per-LLM-call budget op because
        # each op re-issues the Mongo call before degrading. The latch routes ops
        # straight to the in-memory fallback for a cooldown window after the first
        # PyMongoError, so steady-state outage cost is ~0 per call (D-08 in
        # aggregate). Exactly one op re-probes Mongo once the cooldown elapses.
        self._degraded_until: float = 0.0
        self._degrade_cooldown_s = int(os.getenv("A0_BUDGET_DEGRADE_COOLDOWN_S", "60"))

    def _fallback(self) -> "InMemoryBudgetTracker":
        """Return the lazily-created in-memory fallback tracker."""
        if self._fallback_tracker is None:
            self._fallback_tracker = InMemoryBudgetTracker()
        return self._fallback_tracker

    def add_spend(self, agent_name: str, cost_usd: float) -> None:
        """
        Add spend atomically using MongoDB $inc.

        Safe for concurrent multi-agent updates.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # WR-02: while the degrade latch is armed, skip the ~5s Mongo op entirely.
        if time.monotonic() < self._degraded_until:
            self._fallback().add_spend(agent_name, cost_usd)
            return

        # Atomic increment (safe for concurrent updates). A down Mongo fast-fails
        # (serverSelectionTimeoutMS) -> degrade to the in-memory fallback + signal;
        # never raise into the per-LLM-call caller.
        try:
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
            self._degraded_until = 0.0  # op succeeded — clear the latch
            SourceHealthRegistry.get_shared_instance().report(
                "budget_mongo", available=True
            )
        except PyMongoError as exc:
            self._degraded_until = time.monotonic() + self._degrade_cooldown_s
            SourceHealthRegistry.get_shared_instance().report(
                "budget_mongo", available=False, failure_reason=type(exc).__name__
            )
            self._fallback().add_spend(agent_name, cost_usd)
            return

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

        # WR-02: while the degrade latch is armed, skip the ~5s Mongo op entirely.
        if time.monotonic() < self._degraded_until:
            return self._fallback().get_daily_total()

        # Fetch from MongoDB. A down Mongo fast-fails (serverSelectionTimeoutMS)
        # -> return the in-memory fallback value + signal; never block/raise.
        today = now.strftime("%Y-%m-%d")
        try:
            doc = self._collection.find_one({"_id": today})
            self._degraded_until = 0.0  # op succeeded — clear the latch
            SourceHealthRegistry.get_shared_instance().report(
                "budget_mongo", available=True
            )
        except PyMongoError as exc:
            self._degraded_until = time.monotonic() + self._degrade_cooldown_s
            SourceHealthRegistry.get_shared_instance().report(
                "budget_mongo", available=False, failure_reason=type(exc).__name__
            )
            return self._fallback().get_daily_total()
        total = doc["total_spend"] if doc else 0.0

        # Update cache
        self._local.cached_total = total
        self._local.cache_time = now

        return total

    def get_agent_spend(self, agent_name: str) -> float:
        """Get daily spend for a specific agent."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # WR-02: while the degrade latch is armed, skip the ~5s Mongo op entirely.
        if time.monotonic() < self._degraded_until:
            return self._fallback().get_agent_spend(agent_name)

        # A down Mongo fast-fails (serverSelectionTimeoutMS) -> return the
        # in-memory fallback value + signal; never block/raise into the caller.
        try:
            doc = self._collection.find_one({"_id": today})
            self._degraded_until = 0.0  # op succeeded — clear the latch
            SourceHealthRegistry.get_shared_instance().report(
                "budget_mongo", available=True
            )
        except PyMongoError as exc:
            self._degraded_until = time.monotonic() + self._degrade_cooldown_s
            SourceHealthRegistry.get_shared_instance().report(
                "budget_mongo", available=False, failure_reason=type(exc).__name__
            )
            return self._fallback().get_agent_spend(agent_name)

        if not doc:
            return 0.0

        return doc.get("agents", {}).get(agent_name, 0.0)
