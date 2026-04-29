"""Adapters to bridge embedding models to QdrantBackend's expected interface."""

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
        vectors = self.embedder.embed_documents(texts)
        return EmbedResponse(
            embeddings=vectors,
            model=kwargs.get("model", "langchain-wrapped"),
            token_count=0,
            cache_hits=0,
        )


class BgeEmbeddingAdapter:
    """Loads BAAI/bge-base-en-v1.5 (768-dim) directly via sentence-transformers.

    Used for knowledge_base and trading_context collections where higher quality
    embeddings are needed for books, research papers, and technical documents.

    Lazy-loads the model on first use to avoid slowing down startup.
    """

    MODEL_NAME = "BAAI/bge-base-en-v1.5"
    VECTOR_DIM = 768

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    async def embed(self, texts: list[str], **kwargs) -> EmbedResponse:
        """Embed texts using bge-base-en-v1.5 (768-dim).

        Accepts and ignores kwargs (project_id, model, normalize) for interface compat.
        """
        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True).tolist()
        return EmbedResponse(
            embeddings=vectors,
            model=self.MODEL_NAME,
            token_count=0,
            cache_hits=0,
        )
