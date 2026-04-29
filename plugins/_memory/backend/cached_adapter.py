"""Caching wrapper for embedding adapters.

Wraps any adapter with async embed(texts, **kwargs) -> EmbedResponse
to add Redis caching transparently. Per-text granularity: only uncached
texts are computed, results merged preserving original order.
"""

import logging
from plugins._memory.backend.embedding_adapter import EmbedResponse

logger = logging.getLogger(__name__)


class CachedEmbeddingAdapter:
    """Wraps an embedding adapter with Redis cache.

    Usage:
        cache = RedisEmbeddingCache(...)
        inner = BgeEmbeddingAdapter()
        cached = CachedEmbeddingAdapter(inner, cache, "BAAI/bge-base-en-v1.5")
        # QdrantBackend uses `cached` as its embedding_service
    """

    def __init__(self, inner_adapter, cache, model_name: str,
                 normalize: bool = True):
        """
        Args:
            inner_adapter: Any adapter with async embed(texts, **kwargs) -> EmbedResponse
            cache: RedisEmbeddingCache instance (or None to disable caching)
            model_name: Model identifier for cache key scoping
            normalize: Whether embeddings are L2-normalized
        """
        self.inner = inner_adapter
        self.cache = cache
        self.model_name = model_name
        self.normalize = normalize

    async def embed(self, texts: list[str], **kwargs) -> EmbedResponse:
        """Embed texts with Redis cache layer.

        For each text: check cache -> batch compute uncached -> store fresh -> merge.
        Falls through to inner adapter if cache is None or Redis is down.
        """
        if not self.cache or not self.cache.is_available():
            return await self.inner.embed(texts, **kwargs)

        n = len(texts)
        results = [None] * n
        uncached_indices = []
        uncached_texts = []
        cache_hits = 0

        # Check cache for each text
        for i, text in enumerate(texts):
            cached = self.cache.get(self.model_name, self.normalize, text)
            if cached is not None:
                results[i] = cached
                cache_hits += 1
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Compute uncached texts
        if uncached_texts:
            response = await self.inner.embed(uncached_texts, **kwargs)
            for j, idx in enumerate(uncached_indices):
                vector = response.embeddings[j]
                results[idx] = vector
                self.cache.set(
                    self.model_name, self.normalize,
                    uncached_texts[j], vector
                )

        if cache_hits > 0:
            logger.info(
                f"Embedding cache: {cache_hits}/{n} hits ({self.model_name})"
            )

        return EmbedResponse(
            embeddings=results,
            model=self.model_name,
            token_count=0,
            cache_hits=cache_hits,
        )
