"""
Write-through MongoDB+Redis cache with monotonic versioning.

Provides:
- Cache-first reads with MongoDB fallback
- Write-through updates (MongoDB → Redis)
- Pub/sub change notifications
- Monotonic version-based optimistic concurrency control
- Graceful degradation when Redis unavailable
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ConcurrentModificationError(Exception):
    """Raised when update fails due to version mismatch."""
    pass


class MongoCachedCollection:
    """
    Write-through cache wrapping a PyMongo collection with Redis.

    Ensures zero MongoDB reads on cache hit. Updates write to MongoDB first
    (authoritative), then mirror to Redis with pub/sub notification.
    """

    def __init__(
        self,
        mongo_collection,
        redis_client,
        cache_prefix: str = "cache",
        ttl: int = 60
    ):
        """
        Initialize write-through cache.

        Args:
            mongo_collection: PyMongo collection instance
            redis_client: Redis client instance
            cache_prefix: Redis key prefix
            ttl: Cache TTL in seconds
        """
        self.collection = mongo_collection
        self.redis = redis_client
        self.cache_prefix = cache_prefix
        self.ttl = ttl

    def _cache_key(self, doc_id: str) -> str:
        """Generate Redis cache key."""
        return f"{self.cache_prefix}:{doc_id}"

    def _pub_channel(self) -> str:
        """Get pub/sub channel name."""
        return f"{self.cache_prefix}:updates"

    def get(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get document by ID. Reads from Redis first, falls back to MongoDB.

        Args:
            doc_id: Document ID

        Returns:
            Document dict or None if not found
        """
        cache_key = self._cache_key(doc_id)

        # Try Redis first
        try:
            cached = self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis get failed for {doc_id}: {e}. Degrading to MongoDB.")

        # Fall back to MongoDB
        doc = self.collection.find_one({"_id": doc_id})
        if doc is None:
            return None

        # Populate cache
        try:
            self.redis.setex(
                cache_key,
                self.ttl,
                json.dumps(doc, default=str)
            )
        except Exception as e:
            logger.warning(f"Redis setex failed for {doc_id}: {e}. Continuing without cache.")

        return doc

    def put(self, doc_id: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Idempotent write-through upsert (Phase 169-04, D-09 compute-at-write-time).

        Unlike ``update`` (which requires an existing doc + version for optimistic
        concurrency), ``put`` upserts the full document — the fit for a cache that writes a
        freshly-computed value keyed by a content fingerprint. Writes MongoDB first
        (authoritative), then mirrors to Redis with the same TTL ``setex`` + graceful
        Redis-down degradation as ``get``/``update``. Additive: no existing behaviour is
        changed.

        Args:
            doc_id: Document ID (also written as ``_id``).
            document: Full document to store.

        Returns:
            The stored document (with ``_id`` set).
        """
        doc = dict(document)
        doc["_id"] = doc_id

        # MongoDB authoritative write (upsert).
        self.collection.replace_one({"_id": doc_id}, doc, upsert=True)

        # Mirror to Redis hot cache with TTL; degrade gracefully if Redis is down.
        cache_key = self._cache_key(doc_id)
        try:
            self.redis.setex(
                cache_key,
                self.ttl,
                json.dumps(doc, default=str)
            )
        except Exception as e:
            logger.warning(f"Redis setex failed for {doc_id}: {e}. Continuing without cache.")

        return doc

    def update(
        self,
        doc_id: str,
        updates: Dict[str, Any],
        current_version: int
    ) -> Dict[str, Any]:
        """
        Update document with version-based optimistic concurrency control.

        Writes to MongoDB first (authoritative), then mirrors to Redis.

        Args:
            doc_id: Document ID
            updates: Fields to update
            current_version: Expected current version (for CAS)

        Returns:
            Updated document

        Raises:
            ConcurrentModificationError: Version mismatch
        """
        # MongoDB write with version check
        result = self.collection.update_one(
            {"_id": doc_id, "version": current_version},
            {
                "$set": updates,
                "$inc": {"version": 1}
            }
        )

        if result.matched_count == 0:
            raise ConcurrentModificationError(
                f"Update failed for {doc_id}: version mismatch (expected {current_version})"
            )

        # Fetch updated document
        updated_doc = self.collection.find_one({"_id": doc_id})

        # Mirror to Redis cache
        cache_key = self._cache_key(doc_id)
        try:
            self.redis.setex(
                cache_key,
                self.ttl,
                json.dumps(updated_doc, default=str)
            )
        except Exception as e:
            logger.warning(f"Redis setex failed for {doc_id}: {e}. Continuing without cache.")

        # Publish notification
        try:
            self.redis.publish(
                self._pub_channel(),
                json.dumps({"doc_id": doc_id, "version": updated_doc.get("version")})
            )
        except Exception as e:
            logger.warning(f"Redis publish failed for {doc_id}: {e}. Continuing without pub/sub.")

        return updated_doc
