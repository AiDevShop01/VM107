"""Tests for CombinedRAGTool."""
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from tools.qdrant.combined_rag import CombinedRAGTool


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
        "memory": {
            "semantic_weight": 0.6,
            "recency_weight": 0.3,
            "outcome_weight": 0.1,
            "recency_decay_hours": 168,
            "default_top_k": 3
        },
        "knowledge": {
            "semantic_weight": 0.8,
            "diversity_weight": 0.2,
            "default_top_k": 5
        }
    }


@pytest.fixture
def combined_rag_tool(mock_agent, mock_qdrant_client, mock_embedding_service, ranking_config):
    """Create CombinedRAGTool instance."""
    # Set class-level dependencies
    CombinedRAGTool.qdrant_client = mock_qdrant_client
    CombinedRAGTool.embedding_service = mock_embedding_service
    CombinedRAGTool.ranking_config = ranking_config

    # Create tool instance with required Tool params
    tool = CombinedRAGTool(
        agent=mock_agent,
        name="combined_rag",
        method=None,
        args={
            "query": "test query",
            "memory_top_k": 3,
            "knowledge_top_k": 5,
            "max_context_tokens": 2000,
            "project_id": "test-project"
        },
        message="",
        loop_data=None
    )
    return tool


class TestCombinedRAGTool:
    """Test CombinedRAGTool functionality."""

    @pytest.mark.asyncio
    async def test_validate_request_creates_contract(self, combined_rag_tool):
        """Test request validation creates CombinedRAGRequest."""
        request = combined_rag_tool._validate_request({
            "query": "test query",
            "memory_top_k": 3,
            "knowledge_top_k": 5,
            "max_context_tokens": 2000,
            "project_id": "test-project"
        })
        assert request.query == "test query"
        assert request.memory_top_k == 3
        assert request.knowledge_top_k == 5
        assert request.max_context_tokens == 2000

    @pytest.mark.asyncio
    async def test_call_vm_embeds_query_once(self, combined_rag_tool, mock_embedding_service):
        """Test that _call_vm embeds query only once (shared between searches)."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        await combined_rag_tool._call_vm(request)

        # Should embed query only once
        assert mock_embedding_service.embed.call_count == 1
        mock_embedding_service.embed.assert_called_with("test query")

    @pytest.mark.asyncio
    async def test_call_vm_searches_both_collections(self, combined_rag_tool, mock_qdrant_client):
        """Test that _call_vm searches both agent_memory and knowledge_base."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        await combined_rag_tool._call_vm(request)

        # Should search both collections
        assert mock_qdrant_client.search.call_count == 2

        # Check collection names in search calls
        calls = mock_qdrant_client.search.call_args_list
        collections = [call.kwargs.get("collection_name") for call in calls]
        assert "agent_memory" in collections
        assert "knowledge_base" in collections

    @pytest.mark.asyncio
    async def test_call_vm_builds_combined_context(self, combined_rag_tool, mock_qdrant_client):
        """Test that _call_vm builds combined_context with memory first, then knowledge."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        # Mock memory results
        memory_result = Mock()
        memory_result.id = "mem-id"
        memory_result.score = 0.8
        memory_result.payload = {
            "id": "mem-id",
            "summary": "Memory result text",
            "type": "insight",
            "project": "test-project",
            "timestamp": "2026-04-26T10:00:00Z"
        }

        # Mock knowledge results
        knowledge_result = Mock()
        knowledge_result.id = "know-id"
        knowledge_result.score = 0.85
        knowledge_result.payload = {
            "text": "Knowledge result text",
            "title": "Test Title",
            "source_type": "book",
            "project": "test-project"
        }

        # Return different results for different collections
        def search_side_effect(*args, **kwargs):
            if kwargs.get("collection_name") == "agent_memory":
                return [memory_result]
            elif kwargs.get("collection_name") == "knowledge_base":
                return [knowledge_result]
            return []

        mock_qdrant_client.search.side_effect = search_side_effect

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        response_data = await combined_rag_tool._call_vm(request)

        # Should have combined_context
        assert "combined_context" in response_data
        assert "AGENT MEMORY" in response_data["combined_context"]
        assert "KNOWLEDGE" in response_data["combined_context"]

        # Memory should appear before knowledge
        memory_idx = response_data["combined_context"].index("AGENT MEMORY")
        knowledge_idx = response_data["combined_context"].index("KNOWLEDGE")
        assert memory_idx < knowledge_idx

    @pytest.mark.asyncio
    async def test_call_vm_respects_token_limit(self, combined_rag_tool, mock_qdrant_client):
        """Test that _call_vm trims context to max_context_tokens."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        # Create many results with long text
        long_text = "This is a very long text that should be truncated. " * 100  # ~5000 chars

        memory_results = []
        for i in range(10):
            result = Mock()
            result.id = f"mem-{i}"
            result.score = 0.8 - (i * 0.05)  # Decreasing scores
            result.payload = {
                "id": f"mem-{i}",
                "summary": long_text,
                "type": "insight",
                "project": "test-project",
                "timestamp": "2026-04-26T10:00:00Z"
            }
            memory_results.append(result)

        knowledge_results = []
        for i in range(10):
            result = Mock()
            result.id = f"know-{i}"
            result.score = 0.85 - (i * 0.05)  # Decreasing scores
            result.payload = {
                "text": long_text,
                "title": f"Title {i}",
                "source_type": "book",
                "project": "test-project"
            }
            knowledge_results.append(result)

        def search_side_effect(*args, **kwargs):
            if kwargs.get("collection_name") == "agent_memory":
                return memory_results
            elif kwargs.get("collection_name") == "knowledge_base":
                return knowledge_results
            return []

        mock_qdrant_client.search.side_effect = search_side_effect

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=10,
            knowledge_top_k=10,
            max_context_tokens=500,  # Small limit
            project_id="test-project"
        )

        response_data = await combined_rag_tool._call_vm(request)

        # Approximate token count: word_count * 1.3
        combined_context = response_data["combined_context"]
        word_count = len(combined_context.split())
        approx_tokens = word_count * 1.3

        # Should be within token limit (with some tolerance for headers)
        assert approx_tokens <= 550  # 10% tolerance

    @pytest.mark.asyncio
    async def test_call_vm_handles_empty_memory_results(self, combined_rag_tool, mock_qdrant_client):
        """Test that _call_vm handles empty memory results gracefully."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        # Only knowledge results
        knowledge_result = Mock()
        knowledge_result.id = "know-id"
        knowledge_result.score = 0.85
        knowledge_result.payload = {
            "text": "Knowledge result text",
            "title": "Test Title",
            "source_type": "book",
            "project": "test-project"
        }

        def search_side_effect(*args, **kwargs):
            if kwargs.get("collection_name") == "agent_memory":
                return []
            elif kwargs.get("collection_name") == "knowledge_base":
                return [knowledge_result]
            return []

        mock_qdrant_client.search.side_effect = search_side_effect

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        response_data = await combined_rag_tool._call_vm(request)

        # Should still have knowledge results
        assert len(response_data["knowledge_results"]) == 1
        assert len(response_data["memory_results"]) == 0
        assert "KNOWLEDGE" in response_data["combined_context"]

    @pytest.mark.asyncio
    async def test_call_vm_handles_empty_knowledge_results(self, combined_rag_tool, mock_qdrant_client):
        """Test that _call_vm handles empty knowledge results gracefully."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        # Only memory results
        memory_result = Mock()
        memory_result.id = "mem-id"
        memory_result.score = 0.8
        memory_result.payload = {
            "id": "mem-id",
            "summary": "Memory result text",
            "type": "insight",
            "project": "test-project",
            "timestamp": "2026-04-26T10:00:00Z"
        }

        def search_side_effect(*args, **kwargs):
            if kwargs.get("collection_name") == "agent_memory":
                return [memory_result]
            elif kwargs.get("collection_name") == "knowledge_base":
                return []
            return []

        mock_qdrant_client.search.side_effect = search_side_effect

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        response_data = await combined_rag_tool._call_vm(request)

        # Should still have memory results
        assert len(response_data["memory_results"]) == 1
        assert len(response_data["knowledge_results"]) == 0
        assert "AGENT MEMORY" in response_data["combined_context"]

    @pytest.mark.asyncio
    async def test_call_vm_handles_all_empty_results(self, combined_rag_tool, mock_qdrant_client):
        """Test that _call_vm returns empty message when both searches empty."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        mock_qdrant_client.search.return_value = []

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        response_data = await combined_rag_tool._call_vm(request)

        # Should return "No relevant context found"
        assert "No relevant context found" in response_data["combined_context"]
        assert len(response_data["memory_results"]) == 0
        assert len(response_data["knowledge_results"]) == 0

    @pytest.mark.asyncio
    async def test_validate_response_creates_contract(self, combined_rag_tool):
        """Test response validation creates CombinedRAGResponse."""
        response_data = {
            "memory_results": [
                {
                    "id": "mem-id",
                    "summary": "Memory text",
                    "type": "insight",
                    "project": "test-project",
                    "timestamp": "2026-04-26T10:00:00Z",
                    "score": 0.8
                }
            ],
            "knowledge_results": [
                {
                    "text": "Knowledge text",
                    "title": "Test Title",
                    "source_type": "book",
                    "project": "test-project",
                    "score": 0.85
                }
            ],
            "combined_context": "Test combined context",
            "metadata": {
                "query_hash": "abcd1234",
                "project_id": "test-project",
                "collections": ["agent_memory", "knowledge_base"],
                "total_hits": 2,
                "result_count": 2,
                "latency_ms": 50,
                "embedding_model": "BAAI/bge-base-en-v1.5",
                "embedding_dimension": 768
            }
        }

        response = combined_rag_tool._validate_response(response_data)
        assert len(response.memory_results) == 1
        assert len(response.knowledge_results) == 1
        assert response.combined_context == "Test combined context"
        assert response.metadata.result_count == 2

    @pytest.mark.asyncio
    async def test_format_response_returns_combined_context(self, combined_rag_tool):
        """Test that _format_response returns combined_context as message."""
        from fingpt_core.contracts.rag.combined import CombinedRAGResponse
        from fingpt_core.contracts.memory.items import MemoryItem
        from fingpt_core.contracts.knowledge.items import KnowledgeItem
        from fingpt_core.contracts.rag.combined import RetrievalMetadata

        memory_items = [
            MemoryItem(
                id="mem-id",
                summary="Memory text",
                type="insight",
                project="test-project",
                timestamp="2026-04-26T10:00:00Z",
                score=0.8
            )
        ]

        knowledge_items = [
            KnowledgeItem(
                text="Knowledge text",
                title="Test Title",
                source_type="book",
                project="test-project",
                score=0.85
            )
        ]

        metadata = RetrievalMetadata(
            query_hash="abcd1234",
            project_id="test-project",
            collections=["agent_memory", "knowledge_base"],
            total_hits=2,
            result_count=2,
            latency_ms=50,
            embedding_model="BAAI/bge-base-en-v1.5",
            embedding_dimension=768
        )

        response = CombinedRAGResponse(
            memory_results=memory_items,
            knowledge_results=knowledge_items,
            combined_context="Test combined context",
            metadata=metadata
        )

        formatted = combined_rag_tool._format_response(response)

        # Should include combined context and metadata summary
        assert "Test combined context" in formatted.message
        assert "2 results" in formatted.message
        assert "50ms" in formatted.message

    @pytest.mark.asyncio
    async def test_metadata_includes_both_collections(self, combined_rag_tool, mock_qdrant_client):
        """Test that RetrievalMetadata.collections includes both collections."""
        from fingpt_core.contracts.rag.combined import CombinedRAGRequest

        request = CombinedRAGRequest(
            query="test query",
            memory_top_k=3,
            knowledge_top_k=5,
            max_context_tokens=2000,
            project_id="test-project"
        )

        response_data = await combined_rag_tool._call_vm(request)

        # Metadata should list both collections
        assert response_data["metadata"]["collections"] == ["agent_memory", "knowledge_base"]
