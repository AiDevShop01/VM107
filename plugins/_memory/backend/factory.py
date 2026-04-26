"""Backend factory for creating MemoryBackend instances from config."""

from typing import Any
from plugins._memory.backend.base import MemoryBackend
from plugins._memory.backend.faiss_backend import FaissBackend
from plugins._memory.backend.qdrant_backend import QdrantBackend


def create_backend(
    config: dict,
    embedding_service: Any | None = None,
) -> MemoryBackend:
    """Create MemoryBackend instance based on config.

    Args:
        config: Configuration dict with memory_backend key
        embedding_service: EmbeddingService instance (required for Qdrant)

    Returns:
        MemoryBackend instance (FaissBackend or QdrantBackend)

    Raises:
        ValueError: If memory_backend value is invalid
        ValueError: If Qdrant selected but embedding_service not provided

    Example config:
        {
            "memory_backend": "faiss",  # or "qdrant"
            "qdrant_host": "192.168.1.151",
            "qdrant_port": 6333,
        }
    """
    backend_type = config.get("memory_backend", "faiss")

    if backend_type == "faiss":
        # FaissBackend wraps existing MyFaiss initialization
        # Agent parameter will be set by Memory.get()
        return FaissBackend(agent=None)

    elif backend_type == "qdrant":
        if embedding_service is None:
            raise ValueError(
                "embedding_service is required for Qdrant backend"
            )

        from qdrant_client import QdrantClient

        # Create QdrantClient from config
        qdrant_host = config.get("qdrant_host", "192.168.1.151")
        qdrant_port = config.get("qdrant_port", 6333)

        client = QdrantClient(host=qdrant_host, port=qdrant_port)

        return QdrantBackend(
            client=client,
            embedding_service=embedding_service,
            collection_name="agent_memory",
        )

    else:
        raise ValueError(
            f"Unknown memory_backend: {backend_type}. "
            f"Valid options: 'faiss', 'qdrant'"
        )
