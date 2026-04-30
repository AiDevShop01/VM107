"""
3-tier batched MongoDB write manager.

Provides:
- Tier 1 (Critical): Immediate writes
- Tier 2 (Important): Batched writes (100 entries or 5s)
- Tier 3 (Metrics): Aggregated $inc writes (500 entries or 30s)
- Ring buffer semantics for max capacity
"""

import logging
import time
from collections import defaultdict, deque
from typing import Any, Dict
from pymongo.operations import UpdateOne

logger = logging.getLogger(__name__)


class TieredBulkWriter:
    """
    Batched MongoDB write manager with 3 tiers.

    Tier 1: Critical writes (immediate)
    Tier 2: Important writes (batched, 100 entries or 5s)
    Tier 3: Metrics writes (aggregated $inc, 500 entries or 30s)
    """

    def __init__(
        self,
        collection,
        tier2_max_size: int = 100,
        tier2_max_seconds: float = 5.0,
        tier3_max_size: int = 500,
        tier3_max_seconds: float = 30.0
    ):
        """
        Initialize tiered bulk writer.

        Args:
            collection: PyMongo collection instance
            tier2_max_size: Tier 2 flush size trigger
            tier2_max_seconds: Tier 2 flush time trigger
            tier3_max_size: Tier 3 flush size trigger
            tier3_max_seconds: Tier 3 flush time trigger
        """
        self.collection = collection

        # Tier 2 settings
        self.tier2_max_size = tier2_max_size
        self.tier2_max_seconds = tier2_max_seconds
        self._tier2_buffer = deque(maxlen=200)  # Ring buffer cap at 200
        self._tier2_last_flush = time.time()

        # Tier 3 settings
        self.tier3_max_size = tier3_max_size
        self.tier3_max_seconds = tier3_max_seconds
        self._tier3_buffer = deque(maxlen=1000)  # Ring buffer cap at 1000
        self._tier3_last_flush = time.time()

    def write_critical(self, doc_id: str, updates: Dict[str, Any]) -> None:
        """
        Write critical update immediately to MongoDB.

        Args:
            doc_id: Document ID
            updates: Fields to update
        """
        self.collection.update_one(
            {"_id": doc_id},
            {"$set": updates}
        )

    def write_important(self, doc_id: str, updates: Dict[str, Any]) -> None:
        """
        Buffer important update. Auto-flushes at size/time trigger.

        Args:
            doc_id: Document ID
            updates: Fields to update
        """
        op = UpdateOne(
            {"_id": doc_id},
            {"$set": updates}
        )
        self._tier2_buffer.append(op)

        # Check triggers
        if len(self._tier2_buffer) >= self.tier2_max_size:
            self._flush_tier2()
        elif time.time() - self._tier2_last_flush >= self.tier2_max_seconds:
            self._flush_tier2()

    def write_metrics(self, doc_id: str, metrics: Dict[str, Any]) -> None:
        """
        Buffer metric $inc update. Auto-flushes at size/time trigger.

        Args:
            doc_id: Document ID
            metrics: Metrics to increment
        """
        # Store as tuple (doc_id, metrics) for later aggregation
        self._tier3_buffer.append((doc_id, metrics))

        # Check triggers
        if len(self._tier3_buffer) >= self.tier3_max_size:
            self._flush_tier3()
        elif time.time() - self._tier3_last_flush >= self.tier3_max_seconds:
            self._flush_tier3()

    def _flush_tier2(self) -> None:
        """Flush Tier 2 buffer to MongoDB."""
        if not self._tier2_buffer:
            return

        ops = list(self._tier2_buffer)
        self._tier2_buffer.clear()
        self._tier2_last_flush = time.time()

        if ops:
            try:
                self.collection.bulk_write(ops, ordered=False)
            except Exception as e:
                logger.error(f"Tier 2 bulk write failed: {e}")

    def _flush_tier3(self) -> None:
        """Flush Tier 3 buffer to MongoDB with aggregation."""
        if not self._tier3_buffer:
            return

        # Aggregate $inc operations by doc_id
        aggregated = defaultdict(lambda: defaultdict(int))
        for doc_id, metrics in self._tier3_buffer:
            for key, value in metrics.items():
                aggregated[doc_id][key] += value

        self._tier3_buffer.clear()
        self._tier3_last_flush = time.time()

        # Build bulk operations
        ops = []
        for doc_id, inc_values in aggregated.items():
            ops.append(UpdateOne(
                {"_id": doc_id},
                {"$inc": inc_values}
            ))

        if ops:
            try:
                self.collection.bulk_write(ops, ordered=False)
            except Exception as e:
                logger.error(f"Tier 3 bulk write failed: {e}")

    def flush_all(self) -> None:
        """Force immediate flush of all tiers (for shutdown)."""
        self._flush_tier2()
        self._flush_tier3()
