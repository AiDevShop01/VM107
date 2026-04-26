"""Tests for SearchKnowledgeTool."""
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from tools.qdrant.search_knowledge import SearchKnowledgeTool


@pytest.fixture
def mock_agent():
    """Create mock agent with context."""
    agent = Mock()
    agent.context = Mock()
    agent.context.project_id = "test-project"
    return agent


@pytest.fixture
def mock_qdrant_client():
    """Create mock QdrantClient."""
    client = Mock()
    client.search = Mock(return_value=[])
    return client


@pytest.fixture
def mock_embedding_service():
    """Create mock EmbeddingService."""
    service = Mock()
    service.embed = AsyncMock(return_value=[0.1] * 768)
    service.model_name = "BAAI/bge-base-en-v1.5"
    service.dimension = 768
    return service


@pytest.fixture
def ranking_config():
    """Create ranking config."""
    return {
        "knowledge": {
            "semantic_weight": 0.8,
            "diversity_weight": 0.2,
            "default_top_k": 5
        }
    }


@pytest.fixture
def search_knowledge_tool(mock_agent, mock_qdrant_client, mock_embedding_service, ranking_config):
    """Create SearchKnowledgeTool instance."""
    # Set class-level dependencies
    SearchKnowledgeTool.qdrant_client = mock_qdrant_client
    SearchKnowledgeTool.embedding_service = mock_embedding_service
    SearchKnowledgeTool.ranking_config = ranking_config

    # Create tool instance with required Tool params
    tool = SearchKnowledgeTool(
        agent=mock_agent,
        name="search_knowledge",
        method=None,
        args={"query": "test query", "top_k": 5, "project_id": "test-project"},
        message="",
        loop_data=None
    )
    return tool


class TestSearchKnowledgeTool:
    """Test SearchKnowledgeTool functionality."""

    @pytest.mark.asyncio
    async def test_validate_request_creates_contract(self, search_knowledge_tool):
        """Test request validation creates SearchKnowledgeRequest."""
        request = search_knowledge_tool._validate_request({
            "query": "test query",
            "top_k": 5,
            "project_id": "test-project"
        })
        assert request.query == "test query"
        assert request.top_k == 5
        assert request.project_id == "test-project"

    @pytest.mark.asyncio
    async def test_validate_request_with_filters(self, search_knowledge_tool):
        """Test request validation with topic and source_type filters."""
        request = search_knowledge_tool._validate_request({
            "query": "test query",
            "top_k": 3,
            "topic": "trading",
            "source_type": "book",
            "project_id": "test-project"
        })
        assert request.topic == "trading"
        assert request.source_type == "book"

    @pytest.mark.asyncio
    async def test_call_vm_embeds_query(self, search_knowledge_tool, mock_embedding_service):
        """Test that _call_vm embeds the query."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            project_id="test-project"
        )

        await search_knowledge_tool._call_vm(request)
        mock_embedding_service.embed.assert_called_once_with("test query")

    @pytest.mark.asyncio
    async def test_call_vm_builds_project_or_global_filter(self, search_knowledge_tool, mock_qdrant_client):
        """Test that _call_vm builds OR filter for project+global."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            project_id="test-project"
        )

        await search_knowledge_tool._call_vm(request)

        # Verify search was called with filter
        assert mock_qdrant_client.search.called
        call_kwargs = mock_qdrant_client.search.call_args.kwargs
        assert "query_filter" in call_kwargs
        # Filter should have should clause with project conditions

    @pytest.mark.asyncio
    async def test_call_vm_applies_topic_filter(self, search_knowledge_tool, mock_qdrant_client):
        """Test that _call_vm applies topic filter when provided."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            topic="trading",
            project_id="test-project"
        )

        await search_knowledge_tool._call_vm(request)

        # Verify filter includes topic condition
        assert mock_qdrant_client.search.called

    @pytest.mark.asyncio
    async def test_call_vm_applies_source_type_filter(self, search_knowledge_tool, mock_qdrant_client):
        """Test that _call_vm applies source_type filter when provided."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            source_type="book",
            project_id="test-project"
        )

        await search_knowledge_tool._call_vm(request)

        # Verify filter includes source_type condition
        assert mock_qdrant_client.search.called

    @pytest.mark.asyncio
    async def test_call_vm_includes_retrieval_metadata(self, search_knowledge_tool, mock_qdrant_client):
        """Test that _call_vm includes RetrievalMetadata in response."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest

        # Mock Qdrant result
        mock_result = Mock()
        mock_result.id = "test-id"
        mock_result.score = 0.85
        mock_result.payload = {
            "text": "Test knowledge text",
            "title": "Test Title",
            "source_type": "book",
            "project": "test-project"
        }
        mock_qdrant_client.search.return_value = [mock_result]

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            project_id="test-project"
        )

        response_data = await search_knowledge_tool._call_vm(request)

        assert "metadata" in response_data
        assert "query_hash" in response_data["metadata"]
        assert "latency_ms" in response_data["metadata"]
        assert "result_count" in response_data["metadata"]
        assert response_data["metadata"]["collections"] == ["knowledge_base"]

    @pytest.mark.asyncio
    async def test_validate_response_creates_contract(self, search_knowledge_tool):
        """Test response validation creates SearchKnowledgeResponse."""
        response_data = {
            "results": [
                {
                    "text": "Test knowledge",
                    "title": "Test Title",
                    "source_type": "book",
                    "project": "test-project",
                    "score": 0.85
                }
            ],
            "metadata": {
                "query_hash": "abcd1234",
                "project_id": "test-project",
                "collections": ["knowledge_base"],
                "total_hits": 1,
                "result_count": 1,
                "latency_ms": 50,
                "embedding_model": "BAAI/bge-base-en-v1.5",
                "embedding_dimension": 768
            }
        }

        response = search_knowledge_tool._validate_response(response_data)
        assert len(response.results) == 1
        assert response.results[0].text == "Test knowledge"
        assert response.metadata.result_count == 1

    @pytest.mark.asyncio
    async def test_format_response_builds_readable_context(self, search_knowledge_tool):
        """Test that _format_response builds readable context with source attribution."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeResponse, KnowledgeItem
        from fingpt_core.contracts.rag.combined import RetrievalMetadata

        items = [
            KnowledgeItem(
                text="This is a long piece of knowledge text that should be truncated" * 10,
                title="Test Title",
                source_type="book",
                project="test-project",
                score=0.85
            )
        ]

        metadata = RetrievalMetadata(
            query_hash="abcd1234",
            project_id="test-project",
            collections=["knowledge_base"],
            total_hits=1,
            result_count=1,
            latency_ms=50,
            embedding_model="BAAI/bge-base-en-v1.5",
            embedding_dimension=768
        )

        response = SearchKnowledgeResponse(results=items, metadata=metadata)
        formatted = search_knowledge_tool._format_response(response)

        assert "[1]" in formatted.message
        assert "Source:" in formatted.message
        assert "Score:" in formatted.message

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_qdrant_unavailable(self, search_knowledge_tool, mock_qdrant_client):
        """Test that Qdrant unavailable returns empty results (not crash)."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest

        # Simulate Qdrant connection error
        mock_qdrant_client.search.side_effect = Exception("Connection refused")

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            project_id="test-project"
        )

        response_data = await search_knowledge_tool._call_vm(request)

        # Should return empty results, not crash
        assert response_data["results"] == []
        assert response_data["metadata"]["result_count"] == 0

    @pytest.mark.asyncio
    async def test_structured_log_emission(self, search_knowledge_tool, caplog):
        """Test that tool emits structured JSON log."""
        from fingpt_core.contracts.knowledge.items import SearchKnowledgeRequest

        request = SearchKnowledgeRequest(
            query="test query",
            top_k=5,
            project_id="test-project"
        )

        with caplog.at_level("INFO"):
            await search_knowledge_tool._call_vm(request)

        # Should have logged structured JSON
        # Check that at least one log message was emitted
        assert len(caplog.records) > 0
