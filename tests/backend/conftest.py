"""Shared fixtures for backend tests."""

import pytest
from unittest.mock import Mock, AsyncMock


@pytest.fixture
def mock_qdrant_client():
    """Mock QdrantClient for testing."""
    client = Mock()
    client.collection_exists = Mock(return_value=False)
    client.create_collection = Mock()
    client.upsert = Mock()
    client.search = Mock(return_value=[])
    client.delete = Mock()
    return client


@pytest.fixture
def mock_embedding_service():
    """Mock EmbeddingService for testing."""
    service = Mock()
    # Mock embed to return a response with embeddings
    mock_response = Mock()
    mock_response.embeddings = [[0.1] * 768]  # 768-dimensional vector
    service.embed = AsyncMock(return_value=mock_response)
    return service


@pytest.fixture
def test_context():
    """Test context with project_id and task_id."""
    context = Mock()
    context.project_id = "test_project"
    context.task_id = "test_task_123"
    context.memory_subdir = "test_project"
    return context
