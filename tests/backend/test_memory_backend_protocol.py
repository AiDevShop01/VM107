"""Test MemoryBackend Protocol compliance."""

import pytest
from plugins._memory.backend.base import MemoryBackend
from plugins._memory.backend.qdrant_backend import QdrantBackend
from plugins._memory.backend.faiss_backend import FaissBackend


def test_qdrant_backend_implements_protocol(mock_qdrant_client, mock_embedding_service):
    """QdrantBackend should implement MemoryBackend Protocol."""
    backend = QdrantBackend(
        client=mock_qdrant_client,
        embedding_service=mock_embedding_service,
        collection_name="agent_memory",
    )
    assert isinstance(backend, MemoryBackend)


def test_faiss_backend_implements_protocol():
    """FaissBackend should implement MemoryBackend Protocol."""
    backend = FaissBackend(agent=None)
    assert isinstance(backend, MemoryBackend)


def test_protocol_has_required_methods():
    """MemoryBackend Protocol should define required methods."""
    required_methods = ["add", "search", "delete", "clear"]
    protocol_methods = [m for m in dir(MemoryBackend) if not m.startswith("_")]
    for method in required_methods:
        assert method in protocol_methods
