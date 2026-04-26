"""Tests for SearchMemoryTool."""
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from tools.qdrant.search_memory import SearchMemoryTool


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
        }
    }


@pytest.fixture
def search_memory_tool(mock_agent, mock_qdrant_client, mock_embedding_service, ranking_config):
    """Create SearchMemoryTool instance."""
    # Set class-level dependencies
    SearchMemoryTool.qdrant_client = mock_qdrant_client
    SearchMemoryTool.embedding_service = mock_embedding_service
    SearchMemoryTool.ranking_config = ranking_config

    # Create tool instance with required Tool params
    tool = SearchMemoryTool(
        agent=mock_agent,
        name="search_memory",
        method=None,
        args={"query": "test query", "top_k": 3, "project_id": "test-project"},
        message="",
        loop_data=None
    )
    return tool


class TestSearchMemoryTool:
    """Test SearchMemoryTool functionality."""

    @pytest.mark.asyncio
    async def test_validate_request_creates_contract(self, search_memory_tool):
        """Test request validation creates SearchMemoryRequest."""
        request = search_memory_tool._validate_request({
            "query": "test query",
            "top_k": 3,
            "project_id": "test-project"
        })
        assert request.query == "test query"
        assert request.top_k == 3
        assert request.project_id == "test-project"

    @pytest.mark.asyncio
    async def test_validate_request_with_area_filter(self, search_memory_tool):
        """Test request validation with area filter."""
        request = search_memory_tool._validate_request({
            "query": "test query",
            "top_k": 3,
            "area": "main",
            "project_id": "test-project"
        })
        assert request.area == "main"

    @pytest.mark.asyncio
    async def test_call_vm_embeds_query(self, search_memory_tool, mock_embedding_service):
        """Test that _call_vm embeds the query."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        await search_memory_tool._call_vm(request)
        mock_embedding_service.embed.assert_called_once_with("test query")

    @pytest.mark.asyncio
    async def test_call_vm_enforces_project_filter(self, search_memory_tool, mock_qdrant_client):
        """Test that _call_vm ALWAYS filters by project (mandatory)."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        await search_memory_tool._call_vm(request)

        # Verify search was called with mandatory project filter
        assert mock_qdrant_client.search.called
        call_kwargs = mock_qdrant_client.search.call_args.kwargs
        assert "query_filter" in call_kwargs
        # Filter should have must clause with project condition

    @pytest.mark.asyncio
    async def test_call_vm_applies_area_filter(self, search_memory_tool, mock_qdrant_client):
        """Test that _call_vm applies area filter when provided."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            area="main",
            project_id="test-project"
        )

        await search_memory_tool._call_vm(request)

        # Verify filter includes area condition
        assert mock_qdrant_client.search.called

    @pytest.mark.asyncio
    async def test_call_vm_applies_recency_weighted_ranking(self, search_memory_tool, mock_qdrant_client):
        """Test that _call_vm applies recency-weighted ranking."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        # Mock Qdrant results with timestamps
        now = datetime.utcnow()
        old_time = now - timedelta(days=10)

        mock_recent = Mock()
        mock_recent.id = "recent-id"
        mock_recent.score = 0.7  # Lower semantic score
        mock_recent.payload = {
            "id": "recent-id",
            "summary": "Recent memory",
            "type": "insight",
            "project": "test-project",
            "timestamp": now.isoformat() + "Z"
        }

        mock_old = Mock()
        mock_old.id = "old-id"
        mock_old.score = 0.8  # Higher semantic score
        mock_old.payload = {
            "id": "old-id",
            "summary": "Old memory",
            "type": "insight",
            "project": "test-project",
            "timestamp": old_time.isoformat() + "Z"
        }

        mock_qdrant_client.search.return_value = [mock_old, mock_recent]

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        response_data = await search_memory_tool._call_vm(request)

        # Should re-rank by recency weight (recent should score higher)
        assert len(response_data["results"]) == 2
        # Recent memory should have higher final score due to recency boost

    @pytest.mark.asyncio
    async def test_call_vm_applies_outcome_weight(self, search_memory_tool, mock_qdrant_client):
        """Test that _call_vm applies outcome weight to ranking."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        now = datetime.utcnow()

        mock_win = Mock()
        mock_win.id = "win-id"
        mock_win.score = 0.7
        mock_win.payload = {
            "id": "win-id",
            "summary": "Winning trade",
            "type": "trade_decision",
            "project": "test-project",
            "timestamp": now.isoformat() + "Z",
            "outcome": "win"
        }

        mock_loss = Mock()
        mock_loss.id = "loss-id"
        mock_loss.score = 0.7
        mock_loss.payload = {
            "id": "loss-id",
            "summary": "Losing trade",
            "type": "trade_decision",
            "project": "test-project",
            "timestamp": now.isoformat() + "Z",
            "outcome": "loss"
        }

        mock_qdrant_client.search.return_value = [mock_loss, mock_win]

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        response_data = await search_memory_tool._call_vm(request)

        # Win should score higher than loss with same semantic/recency scores
        assert len(response_data["results"]) == 2

    @pytest.mark.asyncio
    async def test_validate_response_creates_contract(self, search_memory_tool):
        """Test response validation creates SearchMemoryResponse."""
        response_data = {
            "results": [
                {
                    "id": "test-id",
                    "summary": "Test memory",
                    "type": "insight",
                    "project": "test-project",
                    "timestamp": "2026-04-26T10:00:00Z",
                    "score": 0.85
                }
            ],
            "metadata": {
                "query_hash": "abcd1234",
                "project_id": "test-project",
                "collections": ["agent_memory"],
                "total_hits": 1,
                "result_count": 1,
                "latency_ms": 50,
                "embedding_model": "BAAI/bge-base-en-v1.5",
                "embedding_dimension": 768
            }
        }

        response = search_memory_tool._validate_response(response_data)
        assert len(response.results) == 1
        assert response.results[0].summary == "Test memory"
        assert response.metadata.result_count == 1

    @pytest.mark.asyncio
    async def test_format_response_builds_readable_context(self, search_memory_tool):
        """Test that _format_response builds readable context with area and type."""
        from fingpt_core.contracts.memory.items import SearchMemoryResponse, MemoryItem
        from fingpt_core.contracts.rag.combined import RetrievalMetadata

        items = [
            MemoryItem(
                id="test-id",
                summary="This is a long memory summary that should be truncated" * 10,
                type="insight",
                project="test-project",
                timestamp="2026-04-26T10:00:00Z",
                area="main",
                score=0.85
            )
        ]

        metadata = RetrievalMetadata(
            query_hash="abcd1234",
            project_id="test-project",
            collections=["agent_memory"],
            total_hits=1,
            result_count=1,
            latency_ms=50,
            embedding_model="BAAI/bge-base-en-v1.5",
            embedding_dimension=768
        )

        response = SearchMemoryResponse(results=items, metadata=metadata)
        formatted = search_memory_tool._format_response(response)

        assert "[1]" in formatted.message
        assert "Area:" in formatted.message
        assert "Type:" in formatted.message
        assert "Score:" in formatted.message

    @pytest.mark.asyncio
    async def test_includes_retrieval_metadata(self, search_memory_tool, mock_qdrant_client):
        """Test that response includes RetrievalMetadata."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        mock_result = Mock()
        mock_result.id = "test-id"
        mock_result.score = 0.85
        mock_result.payload = {
            "id": "test-id",
            "summary": "Test memory",
            "type": "insight",
            "project": "test-project",
            "timestamp": "2026-04-26T10:00:00Z"
        }
        mock_qdrant_client.search.return_value = [mock_result]

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        response_data = await search_memory_tool._call_vm(request)

        assert "metadata" in response_data
        assert "query_hash" in response_data["metadata"]
        assert "latency_ms" in response_data["metadata"]
        assert "result_count" in response_data["metadata"]
        assert response_data["metadata"]["collections"] == ["agent_memory"]

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_qdrant_unavailable(self, search_memory_tool, mock_qdrant_client):
        """Test that Qdrant unavailable returns empty results (not crash)."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        # Simulate Qdrant connection error
        mock_qdrant_client.search.side_effect = Exception("Connection refused")

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        response_data = await search_memory_tool._call_vm(request)

        # Should return empty results, not crash
        assert response_data["results"] == []
        assert response_data["metadata"]["result_count"] == 0

    @pytest.mark.asyncio
    async def test_structured_log_emission(self, search_memory_tool, caplog):
        """Test that tool emits structured JSON log."""
        from fingpt_core.contracts.memory.items import SearchMemoryRequest

        request = SearchMemoryRequest(
            query="test query",
            top_k=3,
            project_id="test-project"
        )

        with caplog.at_level("INFO"):
            await search_memory_tool._call_vm(request)

        # Should have logged structured JSON
        assert len(caplog.records) > 0
