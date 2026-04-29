"""Redis-based embedding cache for VM107.

Inlined from fingpt_core.embedding.cache (VM107 cannot import fingpt_core in Docker).
Provides persistent, shared embedding cache with graceful degradation.
"""

import ast
import hashlib
import logging

logger = logging.getLogger(__name__)


class RedisEmbeddingCache:
    """Redis cache for embedding vectors with graceful degradation.

    Cache key format: embedcache:<sha256(model:normalize:text)>
    Embeddings are deterministic for a given model+text, so project_id
    is not included in the key (same text = same vector regardless of project).
    """

    def __init__(self, host: str = "localhost", port: int = 6379,
                 ttl: int = 604800, redis_url: str | None = None):
        """Initialize Redis cache.

        Args:
            host: Redis host (default: localhost)
            port: Redis port (default: 6379)
            ttl: Time-to-live in seconds (default: 604800 = 7 days)
            redis_url: Full Redis URL (overrides host/port if set)
        """
        import redis as redis_lib
        if redis_url:
            self.client = redis_lib.from_url(redis_url, decode_responses=True)
        else:
            self.client = redis_lib.Redis(host=host, port=port, decode_responses=True)
        self.ttl = ttl
        self._available = None

    def is_available(self) -> bool:
        """Check if Redis is reachable (cached after first successful check)."""
        if self._available is None:
            try:
                self.client.ping()
                self._available = True
                logger.info("Redis embedding cache connected")
            except Exception as e:
                self._available = False
                logger.warning(f"Redis embedding cache unavailable: {e}")
        return self._available

    def _build_key(self, model: str, normalize: bool, text: str) -> str:
        """Build deterministic cache key from embedding parameters."""
        key_input = f"{model}:{normalize}:{text}"
        key_hash = hashlib.sha256(key_input.encode()).hexdigest()
        return f"embedcache:{key_hash}"

    def get(self, model: str, normalize: bool, text: str) -> list[float] | None:
        """Get cached embedding vector.

        Returns:
            Cached vector if found, None otherwise (including on Redis errors).
        """
        try:
            cached = self.client.get(self._build_key(model, normalize, text))
            if cached is None:
                return None
            return ast.literal_eval(cached)
        except Exception as e:
            logger.warning(f"Redis cache get failed: {e}")
            return None

    def set(self, model: str, normalize: bool, text: str,
            vector: list[float]) -> None:
        """Store embedding vector in cache with TTL."""
        try:
            key = self._build_key(model, normalize, text)
            self.client.setex(key, self.ttl, str(vector))
        except Exception as e:
            logger.warning(f"Redis cache set failed: {e}")
