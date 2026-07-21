"""core.embeddings — Phase 58 EmbeddingService bridge (Plan 87-14, additive).

The macro-story-tracker runner imports ``from core.embeddings import
EmbeddingService`` and constructs it with no args (``EmbeddingService()``). The
episodic-memory consumer then calls ``embedding_service.embed(text) -> list[float]``
— a synchronous, single 768-dim vector in **all-mpnet-base-v2** space, matching
the existing Qdrant macro-episode collection (see
``core/memory/qdrant_macro_episode_collection.py``: "768-dim ... all-mpnet-base-v2
embedding space").

This is a thin, additive adapter over the real embedding infrastructure
(``fingpt_core.embedding.LocalCPURunner``). No existing module is modified.
"""
from __future__ import annotations

# Must match the vector space the existing macro-episode collection was built in.
# A mismatch here would silently corrupt cosine similarity, so it is pinned.
_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


class EmbeddingService:
    """Synchronous 768-dim all-mpnet-base-v2 embedding service.

    Wraps ``fingpt_core.embedding.LocalCPURunner`` and exposes the minimal
    ``embed(text) -> list[float]`` contract the macro episodic-memory path
    expects. The SentenceTransformer model loads once at construction time.
    """

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        from fingpt_core.embedding import LocalCPURunner

        self._model_name = model_name
        self._runner = LocalCPURunner(model_name=model_name)

    def embed(self, text: str) -> list[float]:
        """Return the normalized 768-dim embedding vector for ``text``."""
        return self._runner.embed_single(
            text, model=self._model_name, normalize=True
        )


__all__ = ["EmbeddingService"]
