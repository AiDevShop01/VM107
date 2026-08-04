"""Adapters to bridge embedding models to QdrantBackend's expected interface."""

import asyncio
import threading
from dataclasses import dataclass


@dataclass
class EmbedResponse:
    """Mimics fingpt_core EmbedResponse for QdrantBackend compatibility."""
    embeddings: list[list[float]]
    model: str
    token_count: int
    cache_hits: int


class EmbeddingAdapter:
    """Wraps a langchain Embeddings object to match QdrantBackend's embedding_service interface.

    Used for agent_memory (384-dim, all-MiniLM-L6-v2 via langchain).

    QdrantBackend calls:
        response = await self.embedding_service.embed(texts=..., project_id=..., model=..., normalize=...)
        vector = response.embeddings[idx]

    Langchain embedders provide:
        vectors = embedder.embed_documents(texts)
    """

    def __init__(self, langchain_embedder):
        self.embedder = langchain_embedder

    async def embed(self, texts: list[str], **kwargs) -> EmbedResponse:
        """Embed texts using the langchain embedder.

        Accepts and ignores kwargs (project_id, model, normalize) for interface compat.
        """
        # Offload the CPU-bound embed off the event loop (A1/D-03)
        vectors = await asyncio.to_thread(self._embed_documents_sync, texts)
        return EmbedResponse(
            embeddings=vectors,
            model=kwargs.get("model", "langchain-wrapped"),
            token_count=0,
            cache_hits=0,
        )

    def _embed_documents_sync(self, texts: list[str]):
        return self.embedder.embed_documents(texts)


class BgeEmbeddingAdapter:
    """Loads BAAI/bge-base-en-v1.5 (768-dim) directly via sentence-transformers.

    Used for knowledge_base and trading_context collections where higher quality
    embeddings are needed for books, research papers, and technical documents.

    Lazy-loads the model on first use to avoid slowing down startup.
    """

    MODEL_NAME = "BAAI/bge-base-en-v1.5"
    VECTOR_DIM = 768

    # Class-level → process-wide singleton (D-06). The model is loaded exactly
    # once and shared across every instance and every to_thread worker thread.
    _model = None
    _model_lock = threading.Lock()   # single-flight across to_thread worker threads (D-02)
    _load_count = 0                  # D-08.2 counter (incremented inside the lock)

    def __init__(self):
        # Model is a class singleton — no per-instance model state.
        pass

    @classmethod
    def _get_model(cls):
        """Double-checked lazy load of the process-wide SentenceTransformer.

        Uses a threading lock, not an async lock: the load runs inside to_thread
        worker threads, which an async lock cannot serialize (RESEARCH Pitfall 3). This
        same lock is the D-02 single-flight guard — a recall arriving mid-preload
        blocks on the in-flight load and reuses it.
        """
        if cls._model is None:                     # fast path, no lock
            with cls._model_lock:
                if cls._model is None:             # double-checked
                    from sentence_transformers import SentenceTransformer
                    cls._model = SentenceTransformer(cls.MODEL_NAME)
                    cls._load_count += 1
        return cls._model

    async def embed(self, texts: list[str], **kwargs) -> EmbedResponse:
        """Embed texts using bge-base-en-v1.5 (768-dim).

        Accepts and ignores kwargs (project_id, model, normalize) for interface compat.
        """
        # load + encode both run in the worker thread (A1/D-03)
        vectors = await asyncio.to_thread(self._embed_sync, texts)
        return EmbedResponse(
            embeddings=vectors,
            model=self.MODEL_NAME,
            token_count=0,
            cache_hits=0,
        )

    def _embed_sync(self, texts: list[str]):
        model = self._get_model()   # class-singleton load happens in the worker thread
        return model.encode(texts, normalize_embeddings=True).tolist()
